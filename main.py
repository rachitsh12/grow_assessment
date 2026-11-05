"""GrowQR 'One Sentence' orchestration skeleton.

  python main.py run                     Day 1 for Priya
  python main.py run --day 2             Priya returns tomorrow (uses memory from the Day 1 run)
  python main.py run --users 50          50 users, same goal, shared caches
  python main.py run -v                  show every step's output + memory notes
  python main.py run --say "Fix my resume for a data analyst job at Infosys"   # intent -> a smaller plan
  python main.py run --fail sage         an agent fails; the flow survives
  python main.py run --company TCS       a different target company
  add --approve to give the user's OK to pending apply / post actions
"""
import argparse
import asyncio
import json
import os
from datetime import date, timedelta

from agents import AGENTS
from agents import grace
from agents.summary import build_card, render_card, state_getter
from cohort import make_users
from core.cost import CostMeter
from core.executor import Config, run_plan
from core.memory import RELEVANT, Memory
from core.plan import PlanError, validate, waves
from core.state import State
from core.trace import Trace
from tools.tools import World

HERE = os.path.dirname(os.path.abspath(__file__))
MEM_PATH = os.path.join(HERE, ".growqr_memory.json")
SENTENCE = "I want a data analyst job at Infosys in Bangalore."
ARTIFACT_AGENT = {"research": "research", "test": "sage", "resume": "mira", "scout": "scout"}


def flatten(arts: dict) -> dict:
    return {f"{name}.{k}": v for name, a in arts.items() for k, v in a["data"].items()}


async def run_user(user, sentence, world, meter, memory, cfg, trace):
    uid = user["id"]
    memory.ingest_profile(user, cfg.today)                              # user's own words are memory too
    recall = memory.recall(uid)                                          # RECALL BEFORE PLANNING
    goal = grace.parse_goal(sentence, user, world.companies())
    trace.header("MEMORY RECALL (before planning)")
    trace.p(f"  sessions={recall['sessions']} notes={recall['n_notes']} scores={recall['scores']} "
            f"artifacts={sorted(recall['artifacts'])}")
    for w in recall["own_words"]:
        trace.p(f"  user said: \"{w['text']}\"  [{w['topic']}/{w['polarity']}]")
    for c in recall["conflicts"]:
        trace.p(f"  CONFLICT: says \"{c['claim']}\" but {c['measured_topic']}={round(c['measured'] * 100)}% -> {c['resolution']}")
    plan = grace.plan(goal, recall, cfg, memory, uid)
    initial = {"goal": goal, "profile": user, "memory.recall": recall,
               "memory.brief": {a: memory.summary_for(uid, a) for a in list(RELEVANT) + ["research", "approval"]}}
    initial.update(flatten({n: a for n, a in ((n, memory.artifact(uid, n)) for n in recall["artifacts"]) if a}))
    state = State(initial)
    validate(plan, state.keys())
    trace.plan(plan, waves(plan))
    trace.header(f"TRACE (day {cfg.day})")
    status, wall, seq = await run_plan(plan, state, world, meter, memory, cfg, trace, AGENTS, uid)
    # persist: artifacts only from steps that actually ran this time
    new = {}
    for name, agent in ARTIFACT_AGENT.items():
        if status.get(agent, {}).get("state") in ("ok", "degraded"):
            new[name] = {k[len(name) + 1:]: v for k, v in state.data.items() if k.startswith(name + ".")}
    actions = {k[len("actions."):]: dict(v) for k, v in state.data.items() if k.startswith("actions.")}
    for who, a in actions.items():                                       # approval gate result -> stored status
        ap = state.data.get(f"approvals.{who}")
        if ap and ap["status"] in ("applied", "posted"):
            a["status"] = ap["status"]
    new["actions"] = actions
    memory.save_artifacts(uid, cfg.today, **new)
    memory.log_session(uid, cfg.day, cfg.today)
    card = state.data.get("card") or build_card(state_getter(state))      # grace_summary down -> fallback card
    return {"state": state, "status": status, "wall": wall, "seq": seq, "card": card, "plan": plan}


def naive_estimate(state, meter, costs):
    """What the lazy design costs: every agent browses (it cannot know which pages need a browser) what it needs."""
    iv = state.data.get("research.interviews") or {"n": 0}
    R, S = iv["n"], (state.data.get("research.resumes") or {}).get("n", 0)
    N = len(state.data.get("research.news") or [])
    pages = {"scout": 1, "sage": 1 + R, "mira": 1 + S, "kai": 1 + R + N, "vera": R, "lyra": 1 + R + S, "nova": N}
    non_web = sum(e.cost for e in meter.entries if e.tool in ("llm", "sandbox.run"))
    return sum(pages.values()) * costs["browse"] + non_web, sum(pages.values())


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run"])
    ap.add_argument("--day", type=int, default=1)
    ap.add_argument("--users", type=int, default=1)
    ap.add_argument("--fail", action="append", default=[], metavar="AGENT")
    ap.add_argument("--flaky", action="append", default=[], metavar="AGENT", help="fails once, succeeds on retry")
    ap.add_argument("--company", default=None)
    ap.add_argument("--say", default=None, metavar="SENTENCE", help="a different sentence (default: the assessment's)")
    ap.add_argument("--verbose", "-v", action="store_true", help="print each step's output and memory notes")
    ap.add_argument("--approve", action="store_true", help="the user OKs pending apply/post actions")
    return ap.parse_args()


async def main():
    a = parse_args()
    data = json.load(open(os.path.join(HERE, "demo_data.json")))
    world = World(data)
    base = data["user"]
    today = date.fromisoformat(data["meta"]["today"]) + timedelta(days=a.day - 1)
    sentence = a.say or (SENTENCE.replace("Infosys", a.company) if a.company else SENTENCE)
    cfg = Config(day=a.day, today=today, fail=set(a.fail), flaky=set(a.flaky), approve=a.approve,
                 company=a.company, days_left=14 - (a.day - 1))
    goal = grace.parse_goal(sentence, base, world.companies())
    if not goal["company"] or not goal["role"]:
        print(f"I need a role and a company in the sentence (got role={goal['role']}, company={goal['company']}).")
        return
    print(f"GrowQR | user says: \"{sentence}\" | day {a.day} ({today})"
          + (f" | injected failure: {', '.join(a.fail)}" if a.fail else ""))

    if a.users > 1:
        return await cohort(a, base, sentence, world, cfg)

    memory = Memory(MEM_PATH)
    if a.day == 1:
        memory.forget(base["id"])                                        # a fresh Day 1 is reproducible
    elif not memory.exists(base["id"]):
        print("  (no Day 1 memory found: run `python main.py run` first; planning as a new user)")
    meter = CostMeter()
    try:
        r = await run_user(base, sentence, world, meter, memory, cfg, Trace(verbose=a.verbose))
    except PlanError as e:
        print(f"PLAN REJECTED: {e}")
        return
    memory.save()
    trace_totals = Trace()
    trace_totals.totals(meter, r["wall"], r["seq"])
    naive, pages = naive_estimate(r["state"], meter, world.costs)
    print(f"  naive design (each agent browses its {pages} pages, Rs 5 each) would cost ~Rs {naive:.2f}; saved ~Rs {naive - meter.total():.2f}")
    render_card(r["card"])


async def cohort(a, base, sentence, world, cfg):
    users = make_users(base, a.users)
    memory = Memory(None)                                               # in-memory: no file for cohort runs
    meters, firsts = [], None
    for i, u in enumerate(users):
        m = CostMeter()
        if i > 0:
            memory.share_artifact(base["id"], u["id"], "research")      # company-level cache, no personal data
        r = await run_user(u, sentence, world, m, memory, cfg, Trace(enabled=(i == 0), verbose=a.verbose))
        meters.append(m)
        if i == 0:
            firsts = r
            Trace().totals(m, r["wall"], r["seq"])
            print(f"\n--- first user done (Rs {m.total():.2f}); running the other {len(users) - 1} quietly ---")
    costs = [m.total() for m in meters]
    total = CostMeter()
    for m in meters:
        total.extend(m)
    rest = costs[1:]
    print("\n=== COHORT COST ===")
    print(f"  users: {len(users)}   TOTAL SPENT: Rs {total.total():.2f}")
    print(f"  user 1 (pays for research): Rs {costs[0]:.2f}   users 2..{len(users)}: avg Rs {sum(rest) / len(rest):.2f}"
          f" (min {min(rest):.2f}, max {max(rest):.2f})")
    for tool, d in total.by_tool().items():
        print(f"  {tool:<12} {d['calls']:>4} paid calls  {d['cached']:>4} cache hits   Rs{d['cost']:>7.2f}")
    naive, _ = naive_estimate(firsts["state"], meters[0], world.costs)
    print(f"  no sharing (50 isolated Day 1 runs): Rs {costs[0] * len(users):.2f}")
    print(f"  naive design (every agent browses):   ~Rs {naive * len(users):.2f}")
    print(f"  per-user average: Rs {total.total() / len(users):.2f}  (vs Rs {costs[0]:.2f} for a lone user)")
    elig = sum(1 for u in users if float(u["education"][0]["score"].split()[0]) < 6.0)
    print(f"  (variations: CGPA, grad year, claimed skills, coding answers, own words; {elig} user(s) below the 6.0 CGPA cutoff)")


if __name__ == "__main__":
    asyncio.run(main())
