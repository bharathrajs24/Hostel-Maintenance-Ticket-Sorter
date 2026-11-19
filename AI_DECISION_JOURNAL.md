# AI Decision Journal

> This is a STARTER. A journal must describe what *you* actually asked an AI and what *you* decided, so edit, delete and add rows to match what really happened. The rows below are the main design decisions in this codebase, written so you can check each one and say whether you accept it.

| # | Decision point | What the AI suggested | What I decided (accept / change / reject) and why | How I checked it |
|---|---|---|---|---|
| 1 | Who judges urgency? | LLM judges using a rubric; Python safety net can only raise urgency | | `tests/test_rules.py::SafetyNetTests` |
| 2 | Trusting the room | Accept the LLM's room only if it is real **and** written in the complaint | | `CheckRoomTests`, red-team test 2 |
| 3 | Water near a switch | Force issue to electrical and urgent in Python, not just in the prompt | | `test_water_near_fittings...` |
| 4 | Bad LLM replies | Retry once, then fallback to `issue = other` (warden triage); stop calling after 3 failures in a row | | `FallbackTests` |
| 5 | Duplicate key | `(room, issue)` dict preloaded from `open_tickets.csv` | | `DuplicateTests` |
| 6 | "overflowing" safety word | Keep it (spec lists it) even though "dustbin overflowing" becomes urgent | | Complaint H25 in `results.csv` |
| 7 | Mock classifier | Keyword stand-in so Python can be tested without a key. Not used for final results | | README, eval header |
| 8 | Spreadsheet safety | Prefix `= + - @` cells with `'` in CSV outputs | | `test_spreadsheet_formula_injection_is_defused` |
| 9 | Judgment Framework wording | AI used a guessed set of "three questions" | | Replace with the exact course wording |

## Things I did NOT accept from the AI (fill in honestly)
-
-

## Lines I can explain without help (practise before Q&A)
Pick any function in `rules.py` and `ticket_sorter.py` and say, in your own words, what each line does. If you can't, rewrite it more simply until you can.
