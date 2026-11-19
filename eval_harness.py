"""eval_harness.py - 6 test complaints with the EXPECTED room, issue and urgency.

Run it:   python eval_harness.py            (real LLM - use this for your submission)
          python eval_harness.py --mock     (offline; only tests the Python rules)

It runs each complaint through the same steps as the real program
(classify -> validate -> room check -> safety net) and compares the FINAL answer
with what we expect. It also shows what the LLM said BEFORE Python checked it,
so you can see which problems the Python rules caught.
"""

import argparse
import sys
from datetime import date

import llm_client
from ticket_sorter import BASE_DIR, analyse_complaint, build_classifier, new_stats

# expected: final room (None = needs more info), issue, urgent
EVAL_CASES = [
    {"name": "Sparks + burning smell", "text": "Sparks coming from the switchboard in A105. Burning smell",
     "room": "A105", "issue": "electrical", "urgent": True},
    {"name": "Plain fan fault, hyphen room", "text": "Fan not working in B-214 since yesterday",
     "room": "B214", "issue": "electrical", "urgent": False},
    {"name": "Leaking tap", "text": "bathroom tap is leaking in C310 water all over the floor",
     "room": "C310", "issue": "plumbing", "urgent": False},
    {"name": "Wifi down", "text": "wifi not working in D112 since morning. nothing loads",
     "room": "D112", "issue": "internet", "urgent": False},
    {"name": "Room does not exist (block E)", "text": "E210 door lock broken",
     "room": None, "issue": "carpentry", "urgent": False},
    {"name": "Water near switch = electrical", "text": "Water dripping near the switch in B-302 bathroom",
     "room": "B302", "issue": "electrical", "urgent": True},
]


def run_eval(classifier, label, prompt_chars=0):
    """Run every case. Returns a list of result dicts."""
    stats = new_stats()
    rows = []
    for case in EVAL_CASES:
        info = analyse_complaint(case["text"], classifier, stats, label, prompt_chars)
        passed = (info["room"] == case["room"] and info["issue"] == case["issue"]
                  and info["urgent"] == case["urgent"])
        rows.append({"case": case, "info": info, "passed": passed})
    return rows


def render_markdown(rows, label):
    passed = sum(1 for r in rows if r["passed"])
    lines = [f"# Eval harness results", "",
             f"Classifier: **{label}**   |   Run date: {date.today().isoformat()}   |   "
             f"Passed: **{passed}/{len(rows)}**", ""]
    if label == "mock":
        lines += ["> These results are from the offline MOCK, not an LLM. They only prove the Python "
                  "rules work. Re-run without --mock for your submission.", ""]
    lines += ["| # | Case | Expected (room / issue / urgent) | LLM said before Python checks | "
              "Final after Python | Result |", "|---|---|---|---|---|---|"]
    for number, r in enumerate(rows, start=1):
        c, i = r["case"], r["info"]
        expected = f"{c['room']} / {c['issue']} / {c['urgent']}"
        raw = f"{i['raw_room']} / {i['raw_issue']} / {i['raw_urgent']}"
        final = f"{i['room']} / {i['issue']} / {i['urgent']}"
        lines.append(f"| {number} | {c['name']} | {expected} | {raw} | {final} | "
                     f"{'PASS' if r['passed'] else 'FAIL'} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Eval harness")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--prompt", default=str(BASE_DIR / "system_prompt.txt"))
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        classifier, label, prompt_chars = build_classifier(args.mock, args.prompt)
    except llm_client.LLMError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2

    if not args.mock and args.delay:             # slow down for free-tier rate limits
        slow, delay = classifier, args.delay

        def classifier(text):
            import time
            time.sleep(delay)
            return slow(text)

    rows = run_eval(classifier, label, prompt_chars)
    report = render_markdown(rows, label)
    print(report)
    out = BASE_DIR / "output"
    out.mkdir(exist_ok=True)
    (out / "eval_results.md").write_text(report, encoding="utf-8")
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
