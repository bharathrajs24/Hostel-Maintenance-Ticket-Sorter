# Cost and latency note

> **Fill in the blanks after your real run.** I cannot see live prices or your API's speed, so the price and timing cells are for you to complete. `python ticket_sorter.py` writes `output/run_stats.json` with the measured numbers.

## 1. How many API calls for one day of input?
- The program makes **one call per complaint**. A day of **N** complaints = **N calls**.
- Complaints with a bad date or empty text make no call.
- Worst case adds one retry for an invalid reply: **up to 2N calls**. Network retries (429/5xx) are extra but rare.
- The spec says "dozens" per day. Example: **25 complaints (this project's input) = 25 calls**, 50 complaints = 50 calls.
- Duplicates are joined *after* the LLM reads them, so repeats still cost one call each (a possible later optimisation: skip the LLM for exact copies).

## 2. Tokens per call (estimate, ~4 characters per token)
| Part | Size |
|---|---|
| System prompt (`system_prompt.txt`, 3,993 characters) | ~1,000 input tokens |
| Complaint wrapped in tags | ~30-60 input tokens |
| JSON reply | ~30-40 output tokens |
| **Per call** | **~1,050 input + ~35 output** |
| **25 calls (one day)** | **~26,000 input + ~900 output** |

## 3. Latency
| Measure | Your measured value (from `run_stats.json`) |
|---|---|
| Average seconds per call | ______ s |
| Slowest call | ______ s |
| Whole run for 25 complaints (with 1 s `--delay`) | ______ s |

Small, fast models usually answer a short extraction like this in about a second or two, but measure your own. Time per day is roughly `N x (average call + delay)`. Calls run one after another, which is fine for a once-a-day batch.

## 4. Estimated cost per day
`cost per day = (input tokens / 1,000,000 x input price) + (output tokens / 1,000,000 x output price)`

| | Value |
|---|---|
| Model used | ______ |
| Input price per 1M tokens (check your provider's pricing page) | ______ |
| Output price per 1M tokens | ______ |
| Input tokens per day (25 complaints) | ~26,000 |
| Output tokens per day | ~900 |
| **Estimated cost per day** | ______ |
| Free tier? | Free-tier keys cost nothing but have rate limits, which is why the program waits `--delay` seconds between calls and retries on 429 |

Tip: input tokens dominate because the system prompt is sent with every call. Many providers discount repeated prompt prefixes (prompt caching), which would cut the input cost further.
