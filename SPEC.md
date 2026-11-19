# Specification: Hostel Maintenance Ticket Sorter

> DRAFT for faculty sign-off (Checkpoint 1). Edit anything that does not match what you agreed with faculty. Spec first, code second.

**Purpose.** Turn free-text hostel complaints into work orders. An LLM reads each complaint; Python checks and routes. The tool never closes a ticket. The warden assigns and closes all work.

## 1. Input files
| File | Columns | Notes |
|---|---|---|
| `data/complaints.csv` | `id,date,complaint` | 25 complaints, dates `YYYY-MM-DD`, written the way students write |
| `data/open_tickets.csv` | `ticket,room,issue,opened` | Tickets from earlier days. Optional extra column `urgent` (yes/no); if absent, treated as not urgent |

## 2. What the LLM returns (per complaint)
`{"room": "A105", "issue": "electrical", "urgent": true, "summary": "Sparks and burning smell from switchboard"}`

| Field | Allowed values | Rule |
|---|---|---|
| room | block letter + 3 digits (`B214`) or `null` | Copied as written (hyphen/space removed). Never guessed, never "corrected" |
| issue | electrical, plumbing, carpentry, cleaning, internet, other | Water near electrical fittings = electrical |
| urgent | true / false (real boolean) | Only sparks, burning smell, shock, water near fittings, flooding. Capitals / "URGENT!!!" do not count |
| summary | text, 10 words or fewer | Longer summaries are cut to 10 words by Python |

## 3. Room rules (Python, `check_room`)
A room is accepted only if: block is A-D, floor is 1-4, room is 01-20, the same room is written in the complaint, and the complaint does not name a second different room. Otherwise `room = null` and the complaint goes to `needs_info.csv`. `B-214`, `b214` and `B 214` all become `B214`.

## 4. Urgency rule
LLM judges urgency using the rubric in `system_prompt.txt`. Python's safety net can only **raise** urgency: any of *spark, shock, burning smell, flood, overflowing, near the switch, short circuit* makes the complaint urgent. Water words + an electrical fitting word (switch, socket, wiring...) make it urgent **and** electrical. Python never lowers urgency.

## 5. Routing and due dates
electrical → Electrician, plumbing → Plumber, carpentry → Carpenter, cleaning → Housekeeping, internet → IT Support, other → Warden Triage (no trade team fits, a human decides).
Due date = complaint date (urgent) or complaint date + 2 days (`datetime.timedelta`).

## 6. How duplicates are found
Dictionary keyed by `(room, issue)`, pre-loaded from `open_tickets.csv`. Complaints are processed oldest date first. If the key exists, the complaint **joins** that ticket (no new ticket). If the complaint is urgent and the ticket is not, the ticket becomes urgent and its due date moves to that complaint's date (never later than before).

## 7. Outputs
`work_orders.csv` (one row per ticket, urgent first, then by team, all joined complaint ids) · `results.csv` (every complaint: new_ticket / duplicate / needs_more_info) · `needs_info.csv` (no valid room, urgent first) · `summary.txt` (urgent tickets, by team, by block, repeat rooms, needs info, run health). Extra: `run_stats.json` (for the cost note).

## 8. Edge cases and decisions
| Case | Decision |
|---|---|
| No room written / invalid room / LLM invented a room | `needs_info.csv`; issue and urgency are kept so an urgent one is still visible |
| Two different rooms in one complaint | `needs_info.csv` (ambiguous) |
| Room written as "room 214 block B" (no letter+digits form) | `needs_info.csv` (not recognised) |
| LLM returns bad JSON / wrong types / unknown issue | Retry once, then fallback: `issue = other` (Warden Triage), room only if exactly one written, safety net still runs |
| API down, bad key, rate-limited | Retry with wait for network/429; after 3 failures in a row stop calling the LLM and use the fallback. Never crashes |
| Bad date or empty complaint row | `needs_more_info` with a reason, no LLM call |
| Bad row in `open_tickets.csv` | Skipped with a WARNING in `summary.txt` |
| LLM disagrees on issue for the same fault ("fan" as electrical vs other) | Two tickets. Known limitation; the warden sees both |
| Shouting "URGENT!!!" | Ignored by Python. LLM prompt tells it to ignore it too |
| Complaint text tries to give the LLM orders | Wrapped in `<complaint>` tags, treated as data; Python validation still runs |
| Spreadsheet formulas in complaint text (`=...`) | Output cells are prefixed with `'` so Excel shows them as text |
| API key | Read from `.env` / environment, never in code, `.env` is git-ignored |

## 9. Human checkpoint
The warden reads every urgent ticket (listed first in `summary.txt`), reads `needs_info.csv`, and assigns and closes all work.
