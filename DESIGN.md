# DESIGN: "One Sentence" career-coach orchestration

Python 3.11+, stdlib only (asyncio, dataclasses, json, sqlite3, argparse). No framework, so every line is explainable.

```
 "I want a data analyst job at Infosys in Bangalore."
        |
   parse_goal ──> intents (keyword patterns, Rs 0)   get_hired | find_job | prepare_interview | fix_resume ...
        |         ──> Memory.recall(user)        (before planning; own words, scores, conflicts, artifacts)
        |
   Grace.plan(goal, recall)  intents -> agents (INTENTS table) -> + hard deps, research, approval, summary
        |                    -> memory trims what is already known
        |                    ──>  PLAN AS DATA  [{id, agent, depends_on, soft, reads, writes, params, why}]
        |                          + skipped[{agent, reason}]   ("not needed for intent" / Day 2 / cohort reuse)
   validate(plan)   no cycles, no missing deps, no overlapping writes, every read has a producer
        |
   Executor: waves (Kahn).  gather() every ready step in a wave.
        |                    each step = ctx(reads snapshot, declared writes, step-local Tools meter)
        |                    commit writes+memory notes only if the step succeeded
        |                    failed step -> soft dependants run degraded, hard dependants are skipped
        v
   w0  research ─────────────────────────────────────────────  (the ONLY step that touches the web)
   w1  scout | sage | mira               (read research.*, never fetch)
   w2  kai | vera | lyra | nova          (read sage scores / mira gaps if present)
   w3  approval gate                      (Scout "apply" + Nova "post" stay pending unless --approve)
   w4  grace_summary  ──> card  ──> Memory.write_back  ──> total Rs + trace
```

## Key choices (and the trade-off in each)
1. **Plan is data, executor is dumb.** Grace emits `Step` records; the executor only walks the DAG. Day 2 and cohort runs are just *different plans* (steps skipped with a recorded reason), not different code paths. Trade-off: Grace is rule-based today (0 llm cost, deterministic); a real LLM planner would need schema validation, which `validate()` already provides.
2. **One `State`, namespaced keys, declared reads/writes.** `ctx.get/put` raise on undeclared keys; writes are buffered and committed atomically on success, so a crashed agent leaves no half-written state. Trade-off: some ceremony per agent, but dependencies are auditable and the trace is automatic.
3. **Research once, share it.** A single added `research` agent is the only caller of `fetch/browse`; every other agent reads `research.*`. Claims carry `{source_url, date}`. 7 agents x N pages becomes 1 pass, and citations are uniform.
4. **Cost-aware tools.** fetch (Rs 0.10) always before browse (Rs 5). Browse only if the fetchable reports are too few (<3). On Infosys we have 4, so both browser-only threads are skipped and the saving is logged with what we may have missed. Cache by `(tool,url)` and by sandbox code hash. `llm` is at most one call per agent, none where templating suffices.
5. **Trust filter on web content.** Metadata screen first (wrong company, stale >3y, lookalike domain on a job post), then content screen (fee/"guaranteed" scam => whole page rejected; injected instructions stripped, page text is data never instructions, and `llm()` refuses prompts that contain injection patterns). Every rejection is logged with a reason.
6. **Memory = append-only notes + artifacts** (`memory.json`). Each agent writes back `fact | score | own_words` notes. Conflicts are kept both ways: the claim "I'm good at SQL" stays, the measured "SQL joins 40%" wins for planning, and the claim only shapes the *tone* of coaching.
7. **Approval is a gate step.** Scout/Nova only create drafts in `actions.*`; only the gate can mark them applied/posted, and only with `--approve`. Unapproved actions carry over to the next day.
8. **Failure isolation.** `--fail <agent>` raises inside the step. Soft dependants degrade (Lyra falls back to Mira's gaps, Vera to claim-vs-evidence), hard dependants are skipped and listed on the card. Transient errors retry once.

## Agent contracts (reads -> writes)
| agent | reads | writes |
|---|---|---|
| research | goal | research.* (job, interviews, test_format, resumes, news, tips, rejected, skipped_browse, confidence) |
| scout | goal, profile, research.job | scout.*, actions.scout |
| sage | goal, profile, research.interviews/job/test_format, memory | test.* (sections, results) |
| mira | profile, research.job/resumes (optional), memory | resume.* (sections, gaps, section_order) |
| kai | goal, profile, research.* (optional), test.results, memory | kai.* |
| vera | goal, profile, research.interviews, test, memory | vera.* |
| lyra | resume.gaps, test.results, research.*, memory | lyra.* |
| nova | profile, research.news, test.results, memory | nova.*, actions.nova |
| approval | actions | approvals |
| grace_summary | everything | card |

## Added while building (what the code actually does)
- **llm cache.** `llm()` output is a pure function of its prompt, so identical prompts are free. Prompts are built from structured data only (never raw page text). This is what makes 50 users cost about Rs 17, and the trade-off is that personalisation only differs where the prompt differs.
- **Cohort cache.** Users 2..N reuse the company-level `research` artifact (no personal data) through the normal planner rule "skip research if a fresh artifact exists", so no special code path.
- **Sage grades by running code**, not by trusting the `note` field: right rows 1.0, valid-but-wrong 0.4, error 0.0. Her INNER JOIN answer scores 40% on `sql:joins`; memory then holds both her claim and the score.
- **Soft vs hard dependencies.** Hard (`scout`, `sage`, `vera`, `lyra` need research): skipped and listed on the card. Soft (`mira`, `kai`, `nova`): run degraded (generic, uncited) instead of disappearing.
- **Day 2 re-plans from memory:** if Day 1's Sage failed, there is no `test` artifact, so Day 2's plan includes Sage again.
- **Fallback card:** if `grace_summary` itself fails, `main.py` builds the card from state without an llm call.
- **Intent selection vs memory.** Intent decides who is *needed*; memory then decides who can be *skipped* because the result is already known. The skip list keeps both kinds of reason ("not needed for intent: fix_resume" vs "scores already known").
- **The card only describes what ran.** A resume-only plan never says "no job found", because Scout was not part of it.
- **What "parallel" means here.** The executor runs each wave with `asyncio.gather`, and the plan's dependency graph is what makes steps safe to run concurrently. The agents themselves contain no real I/O waits (tools are stubs), so in this skeleton they execute one after another and wave time is *simulated* as the slowest step (sequential time is printed next to it). With real network tools the same code overlaps the waits unchanged.

