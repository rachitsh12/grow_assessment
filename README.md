# GrowQR "One Sentence": orchestration skeleton

Python 3.11+, stdlib only. Design and diagram: [DESIGN.md](DESIGN.md).

## Run
```
python3 main.py run                     # Day 1 for Priya: plan, trace, total cost, summary card
python3 main.py run --day 2             # she returns tomorrow (reads the memory file written by Day 1)
python3 main.py run --users 50          # 50 users, same goal, shared caches; prints the cohort cost
python3 main.py run --say "Fix my resume for a data analyst job at Infosys in Bangalore"   # intent -> smaller plan
python3 main.py run -v                  # show every step's output and the memory notes it wrote
python3 main.py run --fail sage         # any agent: research scout sage mira kai vera lyra nova approval grace_summary
python3 main.py run --flaky mira        # fails once, succeeds on retry
python3 main.py run --company TCS       # stretch: other company (2 reports, no job post -> says so)
python3 main.py run --approve           # the user OKs pending "apply" / "post" (add to --day 2 to approve the carried-over ones)
python3 -m unittest discover -s tests -t .
```
`run` (Day 1) resets Priya's memory (`.growqr_memory.json`). `--users` never touches the file.

## How Grace picks agents (intent mapping)
The sentence is parsed into intents with keyword patterns (no llm cost), each intent maps to agents, and Grace adds what they need (hard dependencies, `research`, `approval`, the summary). Memory then skips what is already known. Every step in the plan shows why it is there.

| Sentence | Intent | Agents | Spend |
|---|---|---|---|
| "I want a data analyst job at Infosys in Bangalore." (the assessment) | get_hired | all 10 | Rs 6.10 |
| "Fix my resume for a data analyst job at Infosys" | fix_resume | research, mira, summary | Rs 2.10 |
| "Help me prepare for my Infosys data analyst interview" | prepare_interview | research, sage, kai, vera, summary | Rs 5.10 |
| "Find me data analyst openings at Infosys" | find_job | research, scout, approval, summary | Rs 1.60 |
| "Build my LinkedIn presence for Infosys data analyst roles" | build_brand | research, nova, approval, summary | Rs 2.10 |

Without a recognised ask Grace falls back to the full package and says so. A sentence with no role or company is rejected with a message.

## How it flows (start to finish)
1. **Intake.** The sentence is parsed into role, company, city and intent. Intent is keyword matching, so it costs nothing. The assessment's sentence is `get_hired`, the full package; "Fix my resume" is a much smaller plan. Before planning, Grace recalls from memory: Priya's own words, scores and saved results.
2. **Plan as data.** Grace maps the intent to agents, then adds what they need: research, the approval step and the summary. Memory removes steps that are already done. Each step records its dependencies, what it reads and writes, and why it is in the plan. A validator rejects cycles, two steps writing the same key, and reads that nobody produces.
3. **Research once.** It is the only step that touches the web. It screens the free metadata first, dropping the TCS pages, the scam page and the stale report, then fetches 11 pages. It skips the two browser-only threads because four fetchable reports are enough, saving Rs 10. Every fact keeps its URL and date.
4. **Waves in parallel.** w1: Scout, Sage, Mira. w2: Kai, Vera, Lyra, Nova. Each step reads only the keys it declared and buffers its writes, which commit only if it succeeds. A hard dependency failure skips a step; a soft one runs it degraded.
5. **What they produce.**
   - Sage runs her SQL in the sandbox; the wrong INNER JOIN scores 40%.
   - Her claim "I'm good at SQL" and the 40% are both kept in memory, but planning follows the measurement.
   - Vera and Kai ask what Infosys actually asked, with source and date.
   - Mira only lists skills her records support.
6. **Approval.** Scout and Nova only draft. Only the approval step can mark something applied or posted, and only with the user's OK (`--approve`).
7. **Close.** Grace builds one summary card. Memory and artifacts are saved, so Day 2 reuses research and scores. The trace shows every step. Day 1 costs Rs 6.10, against about Rs 160 if every agent browsed.

```
sentence -> intents + role/company/city -> recall memory -> plan (validated)
  w0 research
  w1 scout | sage | mira
  w2 kai | vera | lyra | nova
  w3 approval  ->  w4 summary card  ->  save memory  ->  cost
```

## What the numbers say (demo data)
| run | spend | why |
|---|---|---|
| Day 1 | Rs 6.10 | 11 fetch (1.10) + 2 sandbox (2.00) + 6 llm (3.00). **0 browse.** A "every agent browses" design is ~Rs 160 |
| Day 2 | Rs 1.50 | research, scout, sage, mira, nova skipped from memory; only vera/kai/summary call llm |
| 50 users | Rs 17.10 | user 1 pays Rs 6.10; users 2-50 share research + sandbox + llm caches (avg Rs 0.22). 50 isolated runs = Rs 305 |



- Intent detection is keyword matching: fine for clear asks, weak on unusual phrasing.

## What I would do next
1. LLM planner: give it the agent catalogue (each `SPEC`, cost, purpose) and the recall, let it choose agents and params, and keep `validate()` as the gate with the intent-mapped plan as the fallback. Add budget awareness: rank optional agents by value per rupee and drop the lowest when the budget is tight.
2. Real sandbox (container / seccomp, no network); the SQLite authorizer is a demo, not isolation.
3. Memory compaction: roll old notes into per-topic summaries, keep latest score per topic, decay stale claims; per-user storage instead of one JSON file.
4. Conflict handling beyond "measurement beats claim": confidence + recency, and ask the user when two sources disagree.
5. Source trust scores per domain instead of regex rules; keep the "page text is data" rule.
6. Real concurrency across users (per-tool rate limits, a semaphore), per-step timeouts, budget caps that make Grace drop optional steps before overspending.
7. Cache invalidation by page date, not a flat 7 days; a proper eval set for the question-frequency extraction.
