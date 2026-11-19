"""red_team.py - 3 tricky inputs the tool must survive.

  1. Shouting "URGENT!!!" about something minor  -> must NOT be urgent
  2. A mistyped room number                       -> must go to needs_info (no guessing)
  3. The same complaint sent three times          -> must become ONE ticket

Run:  python red_team.py            (real LLM - use this for your submission)
      python red_team.py --mock     (offline; tests the Python rules only)
"""

import argparse
import sys
import time
from datetime import date

import llm_client
from ticket_sorter import (BASE_DIR, STATUS_DUPLICATE, STATUS_NEEDS_INFO, STATUS_NEW,
                           analyse_complaint, build_classifier, new_stats, process_complaints)

SHOUTING = "URGENT!!! URGENT!!! My dustbin was not emptied today, room C-108, COME IMMEDIATELY!!!"
MISTYPED = "Fan not working in B-241 since yesterday"      # room 41 does not exist (rooms are 01-20)
REPEATED = "Tap is dripping in A-115, please fix"


def run_red_team(classifier, label, prompt_chars=0):
    """Returns a list of {name, input, expected, actual, passed}."""
    stats = new_stats()
    outcomes = []

    info = analyse_complaint(SHOUTING, classifier, stats, label, prompt_chars)
    outcomes.append({
        "name": "1. Shouts URGENT about something minor", "input": SHOUTING,
        "expected": "urgent = False, issue = cleaning, room = C108",
        "actual": f"urgent = {info['urgent']}, issue = {info['issue']}, room = {info['room']}",
        "passed": info["urgent"] is False and info["issue"] == "cleaning" and info["room"] == "C108"})

    info = analyse_complaint(MISTYPED, classifier, stats, label, prompt_chars)
    outcomes.append({
        "name": "2. Mistyped room number", "input": MISTYPED,
        "expected": "room = None (needs more info), NOT 'corrected' to B214",
        "actual": f"room = {info['room']} (LLM said {info['raw_room']}); {info['room_reason']}",
        "passed": info["room"] is None})

    rows = [{"id": f"RT{n}", "date": "2026-10-09", "complaint": REPEATED} for n in (1, 2, 3)]
    tickets = {}
    results = process_complaints(rows, tickets, classifier, stats, label, prompt_chars,
                                 delay=0, verbose=False)
    statuses = [r["status"] for r in results]
    ticket = next(iter(tickets.values())) if tickets else None
    outcomes.append({
        "name": "3. Same complaint sent 3 times", "input": REPEATED + "  (x3)",
        "expected": "1 ticket, statuses = new_ticket, duplicate, duplicate, 3 complaints joined",
        "actual": f"{len(tickets)} ticket(s), statuses = {statuses}, "
                  f"joined = {len(ticket['complaint_ids']) if ticket else 0}",
        "passed": (len(tickets) == 1 and statuses == [STATUS_NEW, STATUS_DUPLICATE, STATUS_DUPLICATE]
                   and len(ticket["complaint_ids"]) == 3)})
    return outcomes


def render_markdown(outcomes, label):
    passed = sum(1 for o in outcomes if o["passed"])
    lines = ["# Red-team results", "",
             f"Classifier: **{label}**   |   Run date: {date.today().isoformat()}   |   "
             f"Passed: **{passed}/{len(outcomes)}**", ""]
    if label == "mock":
        lines += ["> These results are from the offline MOCK, not an LLM. Re-run without --mock "
                  "for your submission.", ""]
    lines += ["| Test | Input | Expected | Actual | Result |", "|---|---|---|---|---|"]
    for o in outcomes:
        lines.append(f"| {o['name']} | {o['input']} | {o['expected']} | {o['actual']} | "
                     f"{'PASS' if o['passed'] else 'FAIL'} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Red-team tests")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--prompt", default=str(BASE_DIR / "system_prompt.txt"))
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        classifier, label, prompt_chars = build_classifier(args.mock, args.prompt)
    except llm_client.LLMError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    if not args.mock and args.delay:
        slow, delay = classifier, args.delay

        def classifier(text):
            time.sleep(delay)
            return slow(text)

    outcomes = run_red_team(classifier, label, prompt_chars)
    report = render_markdown(outcomes, label)
    print(report)
    out = BASE_DIR / "output"
    out.mkdir(exist_ok=True)
    (out / "red_team_results.md").write_text(report, encoding="utf-8")
    return 0 if all(o["passed"] for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
