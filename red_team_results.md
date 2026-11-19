# Red-team results

Classifier: **mock**   |   Run date: 2026-11-19   |   Passed: **3/3**

> These results are from the offline MOCK, not an LLM. Re-run without --mock for your submission.

| Test | Input | Expected | Actual | Result |
|---|---|---|---|---|
| 1. Shouts URGENT about something minor | URGENT!!! URGENT!!! My dustbin was not emptied today, room C-108, COME IMMEDIATELY!!! | urgent = False, issue = cleaning, room = C108 | urgent = False, issue = cleaning, room = C108 | PASS |
| 2. Mistyped room number | Fan not working in B-241 since yesterday | room = None (needs more info), NOT 'corrected' to B214 | room = None (LLM said B241); room 41 does not exist (rooms are 01-20) | PASS |
| 3. Same complaint sent 3 times | Tap is dripping in A-115, please fix  (x3) | 1 ticket, statuses = new_ticket, duplicate, duplicate, 3 complaints joined | 1 ticket(s), statuses = ['new_ticket', 'duplicate', 'duplicate'], joined = 3 | PASS |
