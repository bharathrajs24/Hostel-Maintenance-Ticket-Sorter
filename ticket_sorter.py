"""ticket_sorter.py - Hostel Maintenance Ticket Sorter (console program).

Run it:
    python ticket_sorter.py --mock            # offline test, no API key needed
    python ticket_sorter.py                   # real LLM (needs a key in .env)
    python ticket_sorter.py --test-one "Fan not working in B-214"    # Checkpoint 2

Flow for every complaint:
    classify()  ->  is_valid()  ->  check_room()  ->  apply_safety_net()
        ->  duplicate check on (room, issue)  ->  assign() + due_date()
Python decides; the warden assigns and closes. This program never closes a ticket.
"""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import llm_client
from llm_client import LLMError
from rules import (apply_safety_net, assign, check_room, due_date, fallback_classify,
                   is_valid, room_in_range, trim_summary, VALID_ISSUES)

BASE_DIR = Path(__file__).resolve().parent

STATUS_NEW = "new_ticket"
STATUS_DUPLICATE = "duplicate"
STATUS_NEEDS_INFO = "needs_more_info"

CIRCUIT_BREAKER_LIMIT = 3   # after 3 failed LLM calls in a row, stop calling it for this run

WORK_ORDER_COLUMNS = ["ticket", "team", "room", "issue", "urgent", "due_date", "overdue", "opened",
                      "origin", "status", "complaint_count", "complaint_ids", "summaries"]
RESULT_COLUMNS = ["id", "date", "complaint", "status", "ticket", "team", "room", "issue", "urgent",
                  "summary", "source", "notes"]
NEEDS_INFO_COLUMNS = ["id", "date", "urgent", "issue", "summary", "complaint", "why_needs_info"]


class InputError(Exception):
    """A problem with an input file that stops the run (with a clear message)."""


# ----------------------------------------------------------------------
# Reading input files
# ----------------------------------------------------------------------
def parse_date(text):
    """'2026-10-08' -> a date object. Raises ValueError if it is not in that format."""
    return datetime.strptime(text.strip(), "%Y-%m-%d").date()


def read_csv_rows(path, required_columns):
    """Read a CSV into a list of dicts. Raises InputError if the file or columns are bad."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:   # utf-8-sig: Excel files
            reader = csv.DictReader(handle)
            names = [name.strip() for name in (reader.fieldnames or [])]
            missing = [col for col in required_columns if col not in names]
            if missing:
                raise InputError(f"{path} is missing column(s): {', '.join(missing)}")
            rows = []
            for row in reader:
                rows.append({(key or "").strip(): (value or "").strip() for key, value in row.items()})
            return rows
    except FileNotFoundError:
        raise InputError(f"file not found: {path}")
    except (OSError, csv.Error, UnicodeDecodeError) as err:
        raise InputError(f"cannot read {path}: {err}")


def load_open_tickets(path):
    """Load tickets that were already open. Returns (tickets dict, warnings list).

    The dict key is (room, issue) - that is how duplicates are found later.
    Bad rows are skipped with a warning instead of crashing the program.
    """
    rows = read_csv_rows(path, ["ticket", "room", "issue", "opened"])
    tickets, warnings = {}, []
    for row in rows:
        label = row.get("ticket") or "(no id)"
        room = re.sub(r"[\s-]", "", row["room"]).upper()
        issue = row["issue"].lower()
        ok, reason = room_in_range(room)
        if not ok:
            warnings.append(f"open ticket {label} skipped: {reason}")
            continue
        if issue not in VALID_ISSUES:
            warnings.append(f"open ticket {label} skipped: unknown issue '{row['issue']}'")
            continue
        try:
            opened = parse_date(row["opened"])
        except ValueError:
            warnings.append(f"open ticket {label} skipped: bad date '{row['opened']}'")
            continue
        if (room, issue) in tickets:
            warnings.append(f"open ticket {label} ignored: {room}/{issue} is already ticket "
                            f"{tickets[(room, issue)]['ticket']}")
            continue
        urgent = row.get("urgent", "").lower() in ("true", "yes", "1")   # optional column
        tickets[(room, issue)] = {
            "ticket": label, "room": room, "issue": issue, "team": assign(issue),
            "urgent": urgent, "opened": opened, "due": due_date(opened, urgent),
            "origin": "existing", "complaint_ids": [], "summaries": [],
        }
    return tickets, warnings


def next_ticket_id(tickets):
    """T001, T002 ... one higher than the biggest number already used."""
    numbers = [int(m.group(1)) for t in tickets.values()
               if (m := re.fullmatch(r"T(\d+)", t["ticket"]))]
    return f"T{(max(numbers) + 1 if numbers else 1):03d}"


# ----------------------------------------------------------------------
# The LLM step, with validation, retry and fallback
# ----------------------------------------------------------------------
def new_stats():
    return {"calls": 0, "failed_calls": 0, "invalid_replies": 0, "fallbacks": 0,
            "total_seconds": 0.0, "max_seconds": 0.0, "est_input_tokens": 0,
            "est_output_tokens": 0, "consecutive_failures": 0, "llm_disabled": False}


def get_classification(complaint, classifier, stats, prompt_chars=0):
    """Ask the LLM, check the reply, retry once if it is invalid, else fall back.

    Returns (clean_result, how, notes). how is 'llm' or 'fallback'.
    One bad reply must never crash the program.
    """
    notes = []
    if not stats["llm_disabled"]:
        for attempt in (1, 2):
            started = time.perf_counter()
            reply = None
            try:
                reply = classifier(complaint)
            except Exception as err:       # deliberately broad: ANY failure -> fallback, no crash
                stats["failed_calls"] += 1
                stats["consecutive_failures"] += 1
                notes.append(f"LLM call failed: {err}")
                if stats["consecutive_failures"] >= CIRCUIT_BREAKER_LIMIT:
                    stats["llm_disabled"] = True
                    print("\n!! LLM failed 3 times in a row - using the fallback for the rest "
                          "of this run. Check your key, model name and internet.\n", file=sys.stderr)
                break                       # no point retrying a hard failure
            finally:
                elapsed = time.perf_counter() - started
                stats["calls"] += 1
                stats["total_seconds"] += elapsed
                stats["max_seconds"] = max(stats["max_seconds"], elapsed)
                stats["est_input_tokens"] += (prompt_chars + len(complaint)) // 4 + 1
                if reply is not None:
                    stats["est_output_tokens"] += len(json.dumps(reply)) // 4 + 1

            ok, why = is_valid(reply)
            if ok:
                stats["consecutive_failures"] = 0
                clean = {"room": reply["room"], "issue": reply["issue"], "urgent": reply["urgent"],
                         "summary": trim_summary(reply["summary"])}
                return clean, "llm", notes
            stats["invalid_replies"] += 1
            notes.append(f"invalid LLM reply (attempt {attempt}): {why}")

    stats["fallbacks"] += 1
    notes.append("used fallback (issue=other, goes to warden triage)")
    return fallback_classify(complaint), "fallback", notes


def analyse_complaint(complaint, classifier, stats, label, prompt_chars=0):
    """Run ONE complaint through classify -> validate -> room check -> safety net."""
    clean, how, notes = get_classification(complaint, classifier, stats, prompt_chars)
    source = label if how == "llm" else "fallback"

    room, room_reason = check_room(clean["room"], complaint)
    if room is None:
        notes.append(f"room rejected: {room_reason}")

    final, safety_notes = apply_safety_net(clean, complaint)
    notes.extend(safety_notes)
    return {"room": room, "room_reason": room_reason, "issue": final["issue"],
            "urgent": final["urgent"], "summary": final["summary"], "source": source,
            "notes": notes, "raw_room": clean["room"], "raw_issue": clean["issue"],
            "raw_urgent": clean["urgent"]}


# ----------------------------------------------------------------------
# One complaint -> ticket (new / joined) or needs-info
# ----------------------------------------------------------------------
def handle_complaint(row, tickets, classifier, stats, label, prompt_chars=0):
    """Process one complaint row. Updates `tickets` and returns one result dict."""
    cid, text = row.get("id", ""), row.get("complaint", "")
    result = {"id": cid, "date": row.get("date", ""), "complaint": text, "status": "", "ticket": "",
              "team": "", "room": "", "issue": "", "urgent": False, "summary": "", "source": "",
              "notes": []}

    try:
        complaint_date = parse_date(row.get("date", ""))
    except ValueError:
        result.update(status=STATUS_NEEDS_INFO, source="none",
                      notes=[f"bad or missing date '{row.get('date', '')}'"])
        return result
    if not text.strip():
        result.update(status=STATUS_NEEDS_INFO, source="none", notes=["empty complaint"])
        return result

    info = analyse_complaint(text, classifier, stats, label, prompt_chars)
    result.update(issue=info["issue"], urgent=info["urgent"], summary=info["summary"],
                  source=info["source"], notes=info["notes"])

    if info["room"] is None:                       # no valid room -> warden follows up
        result["status"] = STATUS_NEEDS_INFO
        return result

    room, issue, urgent = info["room"], info["issue"], info["urgent"]
    result.update(room=room, team=assign(issue))
    key = (room, issue)                            # <- the duplicate key

    if key in tickets:                             # JOIN the existing ticket
        ticket = tickets[key]
        ticket["complaint_ids"].append(cid)
        ticket["summaries"].append(info["summary"])
        if urgent and not ticket["urgent"]:        # an urgent repeat makes the ticket urgent
            ticket["urgent"] = True
            ticket["due"] = min(ticket["due"], due_date(complaint_date, True))
            result["notes"].append(f"ticket {ticket['ticket']} upgraded to urgent")
        result.update(status=STATUS_DUPLICATE, ticket=ticket["ticket"])
    else:                                          # NEW ticket
        ticket_id = next_ticket_id(tickets)
        tickets[key] = {"ticket": ticket_id, "room": room, "issue": issue, "team": assign(issue),
                        "urgent": urgent, "opened": complaint_date,
                        "due": due_date(complaint_date, urgent), "origin": "new",
                        "complaint_ids": [cid], "summaries": [info["summary"]]}
        result.update(status=STATUS_NEW, ticket=ticket_id)
    return result


def process_complaints(rows, tickets, classifier, stats, label, prompt_chars=0, delay=0.0,
                       verbose=True):
    """Process every complaint, oldest date first. Returns the list of result dicts."""
    def sort_key(row):
        try:
            return parse_date(row.get("date", ""))
        except ValueError:
            return datetime.max.date()       # bad dates go last
    ordered = sorted(rows, key=sort_key)     # sorted() is stable: same-day rows keep file order

    results = []
    for number, row in enumerate(ordered, start=1):
        result = handle_complaint(row, tickets, classifier, stats, label, prompt_chars)
        results.append(result)
        if verbose:
            urgent_flag = " URGENT" if result["urgent"] else ""
            print(f"[{number:>2}/{len(ordered)}] {result['id']:<5} {result['status']:<16} "
                  f"{result['ticket'] or '-':<5} {result['room'] or '?':<5} "
                  f"{result['issue'] or '-':<10}{urgent_flag}")
        if delay and number < len(ordered):
            time.sleep(delay)                # be gentle with free-tier rate limits
    return results


# ----------------------------------------------------------------------
# Writing the output files
# ----------------------------------------------------------------------
def safe_cell(value):
    """Stop spreadsheet formula injection: a cell starting with = + - @ is shown as text."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: safe_cell(row.get(col, "")) for col in columns})


def sorted_tickets(tickets):
    """Urgent first, then grouped by team, then earliest due date."""
    return sorted(tickets.values(),
                  key=lambda t: (0 if t["urgent"] else 1, t["team"], t["due"], t["ticket"]))


def write_reports(tickets, results, out_dir, stats, as_of, warnings=(), label=""):
    """Write work_orders.csv, results.csv, needs_info.csv, summary.txt (+ run_stats.json)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ordered = sorted_tickets(tickets)
    work_rows = []
    for t in ordered:
        work_rows.append({
            "ticket": t["ticket"], "team": t["team"], "room": t["room"], "issue": t["issue"],
            "urgent": t["urgent"], "due_date": t["due"].isoformat(),
            "overdue": "yes" if t["due"] < as_of else "no", "opened": t["opened"].isoformat(),
            "origin": t["origin"], "status": "open - warden to assign",
            "complaint_count": len(t["complaint_ids"]), "complaint_ids": t["complaint_ids"],
            "summaries": " | ".join(t["summaries"]),
        })
    write_csv(out_dir / "work_orders.csv", WORK_ORDER_COLUMNS, work_rows)

    result_rows = [dict(r, notes="; ".join(r["notes"])) for r in results]
    write_csv(out_dir / "results.csv", RESULT_COLUMNS, result_rows)

    needs = [r for r in results if r["status"] == STATUS_NEEDS_INFO]
    needs.sort(key=lambda r: (0 if r["urgent"] else 1, r["date"], r["id"]))
    needs_rows = [dict(r, why_needs_info="; ".join(r["notes"])) for r in needs]
    write_csv(out_dir / "needs_info.csv", NEEDS_INFO_COLUMNS, needs_rows)

    (out_dir / "summary.txt").write_text(
        build_summary(ordered, results, as_of, stats, warnings, label), encoding="utf-8")

    calls = stats["calls"]
    run_stats = dict(stats, average_seconds=round(stats["total_seconds"] / calls, 3) if calls else 0,
                     total_seconds=round(stats["total_seconds"], 3),
                     max_seconds=round(stats["max_seconds"], 3), complaints=len(results))
    (out_dir / "run_stats.json").write_text(json.dumps(run_stats, indent=2), encoding="utf-8")


def build_summary(ordered, results, as_of, stats, warnings, label):
    """Make the text of summary.txt."""
    count = lambda status: sum(1 for r in results if r["status"] == status)
    lines = ["HOSTEL MAINTENANCE TICKET SUMMARY", "=" * 34,
             f"As-of date: {as_of.isoformat()}   (latest complaint date in the input)",
             f"Complaints processed: {len(results)}  ->  new tickets: {count(STATUS_NEW)}, "
             f"joined as duplicates: {count(STATUS_DUPLICATE)}, "
             f"needs more info: {count(STATUS_NEEDS_INFO)}",
             f"Read by: {label or 'n/a'} ({sum(1 for r in results if r['source'] == label)}), "
             f"fallback ({sum(1 for r in results if r['source'] == 'fallback')})",
             "The tool never closes tickets. The warden assigns and closes all work.", ""]

    lines.append("URGENT TICKETS - WARDEN READS THESE FIRST")
    urgent = [t for t in ordered if t["urgent"]]
    if urgent:
        for t in urgent:
            lines.append(f"  {t['ticket']}  {t['room']}  {t['issue']:<10} -> {t['team']:<13} "
                         f"due {t['due'].isoformat()}  ({'; '.join(t['summaries']) or 'carried over'})")
    else:
        lines.append("  (none)")

    lines += ["", "TICKETS BY TEAM (all open tickets, including ones carried over)"]
    teams = sorted({t["team"] for t in ordered})
    for team in teams:
        mine = [t for t in ordered if t["team"] == team]
        lines.append(f"  {team:<14} {len(mine):>2}   ({sum(1 for t in mine if t['urgent'])} urgent)")

    lines += ["", "TICKETS BY BLOCK"]
    for block in "ABCD":
        mine = [t for t in ordered if t["room"][0] == block]
        lines.append(f"  Block {block}  {len(mine):>2}   ({sum(1 for t in mine if t['urgent'])} urgent)")

    lines += ["", "ROOMS WITH REPEAT COMPLAINTS (same room and issue reported more than once)"]
    repeats = []
    for t in ordered:
        reports = len(t["complaint_ids"]) + (1 if t["origin"] == "existing" else 0)
        if reports >= 2:
            earlier = " + earlier open ticket" if t["origin"] == "existing" else ""
            repeats.append(f"  {t['room']}  {t['issue']:<10} {reports} reports{earlier}  "
                           f"-> {t['ticket']} (new complaints: {', '.join(t['complaint_ids'])})")
    lines += repeats or ["  (none)"]

    lines += ["", "NEEDS MORE INFO (see needs_info.csv)"]
    needs = [r for r in results if r["status"] == STATUS_NEEDS_INFO]
    for r in sorted(needs, key=lambda r: (0 if r["urgent"] else 1, r["id"])):
        flag = "URGENT " if r["urgent"] else ""
        reason = next((n for n in r["notes"] if n.startswith(("room rejected", "bad", "empty"))), "")
        lines.append(f"  {r['id']:<5} {flag}{reason}")
    if not needs:
        lines.append("  (none)")

    lines += ["", "HEALTH OF THIS RUN",
              f"  LLM calls: {stats['calls']}, failed: {stats['failed_calls']}, "
              f"invalid replies: {stats['invalid_replies']}, fallbacks used: {stats['fallbacks']}"]
    for warning in warnings:
        lines.append(f"  WARNING: {warning}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------
def build_classifier(use_mock, prompt_path):
    """Return (classifier function, label, prompt length)."""
    if use_mock:
        return llm_client.mock_classify, "mock", 0
    llm_client.load_env_file(BASE_DIR / ".env")
    settings = llm_client.get_settings()
    prompt = llm_client.load_system_prompt(prompt_path)

    def classifier(text):
        return llm_client.classify(text, settings, prompt)
    return classifier, settings["provider"], len(prompt)


def parse_args(argv):
    p = argparse.ArgumentParser(description="Hostel Maintenance Ticket Sorter")
    p.add_argument("--complaints", default=str(BASE_DIR / "data" / "complaints.csv"))
    p.add_argument("--open-tickets", default=str(BASE_DIR / "data" / "open_tickets.csv"))
    p.add_argument("--out", default=str(BASE_DIR / "output"))
    p.add_argument("--prompt", default=str(BASE_DIR / "system_prompt.txt"))
    p.add_argument("--mock", action="store_true",
                   help="use the offline keyword mock instead of the LLM (for testing only)")
    p.add_argument("--delay", type=float, default=1.0,
                   help="seconds to wait between LLM calls (free tiers have rate limits)")
    p.add_argument("--as-of", help="date used to flag overdue tickets, YYYY-MM-DD "
                                   "(default: latest complaint date)")
    p.add_argument("--test-one", metavar="TEXT",
                   help="Checkpoint 2: send ONE complaint to the LLM and print the JSON")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        classifier, label, prompt_chars = build_classifier(args.mock, args.prompt)
    except LLMError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    if args.test_one:                                   # Checkpoint 2
        try:
            reply = classifier(args.test_one)
        except LLMError as err:
            print(f"ERROR: {err}", file=sys.stderr)
            return 1
        print(json.dumps(reply, indent=2, ensure_ascii=False))
        ok, why = is_valid(reply)
        print("valid JSON shape" if ok else f"INVALID: {why}")
        return 0 if ok else 1

    try:
        rows = read_csv_rows(args.complaints, ["id", "date", "complaint"])
        tickets, warnings = load_open_tickets(args.open_tickets)
    except InputError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    print(f"Read {len(rows)} complaints and {len(tickets)} open tickets. Classifier: {label}")
    stats = new_stats()
    delay = 0.0 if args.mock else args.delay
    results = process_complaints(rows, tickets, classifier, stats, label, prompt_chars, delay)

    dates = []
    for row in rows:
        try:
            dates.append(parse_date(row["date"]))
        except ValueError:
            pass
    try:
        as_of = parse_date(args.as_of) if args.as_of else (max(dates) if dates else datetime.now().date())
    except ValueError:
        print("ERROR: --as-of must look like 2026-10-09", file=sys.stderr)
        return 2

    try:
        write_reports(tickets, results, args.out, stats, as_of, warnings, label)
    except OSError as err:
        print(f"ERROR: cannot write output files: {err}", file=sys.stderr)
        return 2

    print(f"\nDone. {len(tickets)} tickets. Files written to {args.out}")
    for name in ("work_orders.csv", "results.csv", "needs_info.csv", "summary.txt"):
        print(f"  - {name}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
