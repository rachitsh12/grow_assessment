"""Plan as data: a list of Step records. Validation catches bad plans before anything runs."""
from dataclasses import dataclass, field, asdict

from core.state import matches, overlaps


class PlanError(Exception):
    pass


@dataclass
class Step:
    id: str
    agent: str
    depends_on: list = field(default_factory=list)
    soft: list = field(default_factory=list)      # dependencies whose failure we tolerate (degrade)
    reads: list = field(default_factory=list)
    optional_reads: list = field(default_factory=list)
    writes: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    why: str = ""


@dataclass
class Plan:
    steps: list
    skipped: list = field(default_factory=list)   # [{agent, reason}]
    notes: list = field(default_factory=list)

    def to_data(self):
        return {"steps": [asdict(s) for s in self.steps], "skipped": self.skipped, "notes": self.notes}


def ancestors(plan: Plan, step_id: str) -> set:
    by_id = {s.id: s for s in plan.steps}
    seen, stack = set(), list(by_id[step_id].depends_on)
    while stack:
        d = stack.pop()
        if d in seen:
            continue
        seen.add(d)
        stack.extend(by_id[d].depends_on)
    return seen


def validate(plan: Plan, initial_keys) -> None:
    by_id = {}
    for s in plan.steps:
        if s.id in by_id:
            raise PlanError(f"duplicate step id {s.id}")
        by_id[s.id] = s
    for s in plan.steps:
        for d in s.depends_on:
            if d not in by_id:
                raise PlanError(f"{s.id} depends on missing step {d}")
        for d in s.soft:
            if d not in s.depends_on:
                raise PlanError(f"{s.id}: soft dep {d} is not in depends_on")
    # cycle check (Kahn)
    indeg = {s.id: len(s.depends_on) for s in plan.steps}
    ready = [i for i, n in indeg.items() if n == 0]
    seen = 0
    while ready:
        n = ready.pop()
        seen += 1
        for s in plan.steps:
            if n in s.depends_on:
                indeg[s.id] -= 1
                if indeg[s.id] == 0:
                    ready.append(s.id)
    if seen != len(plan.steps):
        raise PlanError("cycle in plan")
    # no two steps write overlapping keys (writes are committed per wave)
    for i, a in enumerate(plan.steps):
        for b in plan.steps[i + 1:]:
            for wa in a.writes:
                for wb in b.writes:
                    if overlaps(wa, wb):
                        raise PlanError(f"{a.id} and {b.id} both write '{wa}'/'{wb}'")
    # every required read has a producer: initial state or an ancestor's declared writes
    initial = list(initial_keys)
    for s in plan.steps:
        anc = ancestors(plan, s.id)
        produced = [w for a in anc for w in by_id[a].writes]
        for r in s.reads:
            ok = any(matches(k, r) or matches(r, k) for k in initial) or \
                 any(matches(w, r) or matches(r, w) for w in produced)
            if not ok:
                raise PlanError(f"{s.id} reads '{r}' but no upstream step or initial state provides it")


def waves(plan: Plan) -> list:
    """Static wave levels (used for display and tests; the executor uses live statuses)."""
    level = {}
    by_id = {s.id: s for s in plan.steps}

    def lv(i):
        if i not in level:
            level[i] = 0 if not by_id[i].depends_on else 1 + max(lv(d) for d in by_id[i].depends_on)
        return level[i]

    out: dict = {}
    for s in plan.steps:
        out.setdefault(lv(s.id), []).append(s.id)
    return [out[k] for k in sorted(out)]
