"""Executor: walks the plan in waves; every ready step in a wave runs concurrently (asyncio.gather).

Rules
- a step runs when all its dependencies have finished (ok / failed / skipped)
- hard dependency failed or skipped  -> step is SKIPPED (listed on the card)
- soft dependency failed or skipped  -> step runs DEGRADED (ctx.degraded says which)
- writes + memory notes are buffered and committed only if the step succeeds (atomic)
- a TransientError is retried once; any other exception marks the step failed and the flow continues
- time is simulated: step = sum of its tool seconds, wave = max over its steps
"""
import asyncio
from dataclasses import dataclass, field

from core.state import Ctx, UndeclaredAccess
from tools.tools import Tools


class TransientError(Exception):
    pass


class InjectedFailure(Exception):
    pass


@dataclass
class Config:
    day: int = 1
    today: object = None
    fail: set = field(default_factory=set)       # agent names / step ids that always fail
    flaky: set = field(default_factory=set)      # fail once, succeed on retry
    approve: bool = False
    company: str | None = None
    days_left: int = 14                          # assumed days before the interview (not in demo data)
    max_retries: int = 1


async def run_plan(plan, state, world, meter, memory, cfg, trace, agents, user_id):
    status: dict = {}
    pending = list(plan.steps)
    wave = -1
    wall = seq = 0.0
    flaky_used: set = set()
    state.data["run.status"] = {}

    async def run_one(step):
        spec = agents[step.agent].SPEC
        degraded = [d for d in step.soft if status[d]["state"] in ("failed", "skipped")]
        tools = Tools(world, meter, step.id)
        ctx = Ctx(step, {"reads": step.reads, "optional_reads": step.optional_reads, "writes": step.writes},
                  state, tools, cfg, user_id, cfg.today, degraded)
        err = None
        for attempt in range(cfg.max_retries + 1):
            try:
                if step.agent in cfg.fail or step.id in cfg.fail:
                    raise InjectedFailure(f"{step.agent} failed (injected with --fail)")
                if (step.agent in cfg.flaky or step.id in cfg.flaky) and step.id not in flaky_used:
                    flaky_used.add(step.id)
                    raise TransientError(f"{step.agent} transient error")
                await agents[step.agent].run(ctx)
                err = None
                break
            except TransientError as e:
                err = e
                ctx.writes.clear()
                ctx.notes.clear()
                ctx.warn(f"retrying after: {e}")
            except Exception as e:  # the flow must survive any agent failure, including UndeclaredAccess
                err = e
                break
        failed = err is not None
        ctx_state = "failed" if failed else ("degraded" if degraded else "ok")
        return {
            "id": step.id, "agent": step.agent, "state": ctx_state, "secs": tools.secs, "cost": tools.cost,
            "reads": sorted(ctx.read_log), "writes": [] if failed else sorted(ctx.writes),
            "tools": tools.summary(), "warnings": ctx.warnings + [f"degraded: ran without {d}" for d in degraded],
            "error": f"{type(err).__name__}: {err}" if failed else None,
            "_writes": {} if failed else ctx.writes, "_notes": [] if failed else ctx.notes,
        }

    while pending:
        ready = [s for s in pending if all(d in status for d in s.depends_on)]
        if not ready:
            raise RuntimeError("no runnable steps (cycle?)")
        wave += 1
        runnable, skipped_now = [], []
        for s in ready:
            blocked = [d for d in s.depends_on if d not in s.soft and status[d]["state"] in ("failed", "skipped")]
            if blocked:
                r = {"id": s.id, "agent": s.agent, "state": "skipped", "secs": 0.0, "cost": 0.0, "reads": [],
                     "writes": [], "tools": "-", "warnings": [], "_writes": {}, "_notes": [],
                     "error": f"skipped: required input from {', '.join(blocked)} unavailable"}
                skipped_now.append(r)
            else:
                runnable.append(s)
            pending.remove(s)
        results = await asyncio.gather(*[run_one(s) for s in runnable])
        for r in results + skipped_now:
            status[r["id"]] = r
        for r in results:                                   # commit in plan order => deterministic
            state.commit(r["_writes"])
            for n in r["_notes"]:
                memory.write(user_id, n, cfg.today)
        state.data["run.status"] = {k: {"state": v["state"], "error": v["error"],
                                        "warnings": v["warnings"], "agent": v["agent"]} for k, v in status.items()}
        wsecs = max([r["secs"] for r in results] or [0.0])
        ssecs = sum(r["secs"] for r in results)
        wall += wsecs
        seq += ssecs
        for r in results + skipped_now:
            trace.step(wave, r)
        if results:
            trace.wave_end(wave, wsecs, ssecs)
    return status, wall, seq
