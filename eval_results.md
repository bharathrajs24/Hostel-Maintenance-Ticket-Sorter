# Eval harness results

Classifier: **mock**   |   Run date: 2026-11-19   |   Passed: **6/6**

> These results are from the offline MOCK, not an LLM. They only prove the Python rules work. Re-run without --mock for your submission.

| # | Case | Expected (room / issue / urgent) | LLM said before Python checks | Final after Python | Result |
|---|---|---|---|---|---|
| 1 | Sparks + burning smell | A105 / electrical / True | A105 / electrical / True | A105 / electrical / True | PASS |
| 2 | Plain fan fault, hyphen room | B214 / electrical / False | B214 / electrical / False | B214 / electrical / False | PASS |
| 3 | Leaking tap | C310 / plumbing / False | C310 / plumbing / False | C310 / plumbing / False | PASS |
| 4 | Wifi down | D112 / internet / False | D112 / internet / False | D112 / internet / False | PASS |
| 5 | Room does not exist (block E) | None / carpentry / False | E210 / carpentry / False | None / carpentry / False | PASS |
| 6 | Water near switch = electrical | B302 / electrical / True | B302 / electrical / True | B302 / electrical / True | PASS |
