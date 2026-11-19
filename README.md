# Hostel Maintenance Ticket Sorter

Console tool that turns hostel complaints into work orders. An **LLM reads** each complaint (room, issue, urgent, summary). **Python checks** the room, adds a safety net, routes to a team, joins repeat complaints into one ticket and sets a due date. It never closes a ticket: **the warden assigns and closes all work.**

Python 3.9+ only. No packages to install (standard library only).

## Quick start
```bash
# 1. Test everything offline first (no key needed). The "mock" is a keyword stand-in, NOT an LLM.
python ticket_sorter.py --mock

# 2. Put your key in .env (never commit it)
cp .env.example .env          # Windows: copy .env.example .env
# edit .env: set LLM_PROVIDER, the matching *_API_KEY, and LLM_MODEL

# 3. Checkpoint 2: one complaint to the real LLM, prints JSON
python ticket_sorter.py --test-one "Sparks coming from the switchboard in A105. Burning smell"

# 4. Checkpoint 3: full run (reads data/*.csv, writes output/*)
python ticket_sorter.py

# 5. Week 15: tests, eval harness, red-team (run WITHOUT --mock for real results)
python -m unittest discover -s tests
python eval_harness.py
python red_team.py
```
Useful options: `--delay 2` (slower, for free-tier rate limits), `--as-of 2026-10-09` (date for overdue flags), `--out some_folder`.

## Supported LLM providers (`.env`)
| `LLM_PROVIDER` | Key variable | Default model (override with `LLM_MODEL`) |
|---|---|---|
| `gemini` (default) | `GEMINI_API_KEY` | gemini-2.5-flash |
| `anthropic` | `ANTHROPIC_API_KEY` | claude-haiku-5-5 |
| `openai` (also OpenAI-compatible via `OPENAI_BASE_URL`) | `OPENAI_API_KEY` | gpt-4o-mini |

Model names change. If you get `HTTP 404`, set `LLM_MODEL` to a model your key can use. If you used a different API in Week 12, add it as one more function in `llm_client.py` (copy `_call_openai`).

## Files
| File | What it does |
|---|---|
| `ticket_sorter.py` | Main program: read CSVs, process each complaint, `write_reports()` |
| `rules.py` | Plain-Python rules: `is_valid`, `check_room`, `apply_safety_net`, `assign`, `due_date`, fallback |
| `llm_client.py` | `classify()` + API calls (key from `.env`), JSON extraction, offline mock |
| `system_prompt.txt` | Prompt built on the 5 roles: Authority, Exemplar, Constraint, Rubric, Metadata (6 examples) |
| `eval_harness.py` | 6 test complaints with expected room/issue/urgency → `output/eval_results.md` |
| `red_team.py` | 3 attacks (URGENT shouting, mistyped room, same complaint x3) → `output/red_team_results.md` |
| `tests/` | 68 unit tests (`python -m unittest discover -s tests`) |
| `data/` | `complaints.csv` (25), `open_tickets.csv` (5) |
| `output/` | `work_orders.csv`, `results.csv`, `needs_info.csv`, `summary.txt`, `run_stats.json` |
| `docs/` | `SPEC.md`, `JUDGMENT_FRAMEWORK.md`, `COST_AND_LATENCY.md`, `AI_DECISION_JOURNAL.md` |

> **The files in `output/` that ship in this zip were produced with `--mock`.** Re-run without `--mock` using your real key and commit those files for your submission.

## How one complaint flows
```
complaint text
  -> classify()            LLM returns JSON                       (llm_client.py)
  -> is_valid()            right keys and types? else retry once, then fallback
  -> check_room()          real room AND written in the complaint? else needs_info.csv
  -> apply_safety_net()    spark/shock/flood... can only RAISE urgency
  -> (room, issue) key     already a ticket (incl. open_tickets.csv)? join it : new ticket
  -> assign() / due_date() team from dict; urgent = same day, else +2 days
  -> write_reports()       four output files
```

## Warden's reading order
1. `summary.txt` - urgent tickets are listed first
2. `needs_info.csv` - complaints without a valid room (urgent ones first)
3. `work_orders.csv` - urgent first, grouped by team, every joined complaint listed

## Before you push to GitHub
- [ ] `.env` is listed in `.gitignore` (it is) and `git status` does **not** show `.env`
- [ ] Run `git init`, then make at least 3 meaningful commits, for example:
  ```bash
  git add .gitignore README.md docs/SPEC.md data/ && git commit -m "Add spec, input data and gitignore"
  git add rules.py llm_client.py system_prompt.txt ticket_sorter.py && git commit -m "Add rules, LLM client and main pipeline"
  git add tests/ eval_harness.py red_team.py output/ docs/ && git commit -m "Add tests, eval harness, red-team, outputs and docs"
  ```
- [ ] Re-run with the real LLM and commit the real `output/` files, eval and red-team results
- [ ] Fill in the blanks in `docs/COST_AND_LATENCY.md` and edit `docs/AI_DECISION_JOURNAL.md`
- [ ] Write your own 400-word reflection (it must be yours)

## Honest notes
- Written before a real key was used: the three provider integrations are tested against faked HTTP replies, not live servers. Run `--test-one` first to confirm yours works.
- "Never submit code you cannot explain line by line." Read each file top to bottom; every function has a one-line docstring and the files are short on purpose.
