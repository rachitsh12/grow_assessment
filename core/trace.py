"""Trace: one line per step (agent, time, state read/written, tools, cost), plus plan and totals."""

import json


def compress(keys):
    """['research.job','research.news'] -> 'research.{job,news}'"""
    groups: dict = {}
    for k in sorted(keys):
        head, _, tail = k.partition(".")
        groups.setdefault(head, []).append(tail)
    parts = []
    for h, tails in groups.items():
        tails = [t for t in tails if t]
        if not tails:
            parts.append(h)
        elif len(tails) == 1:
            parts.append(f"{h}.{tails[0]}")
        else:
            parts.append(f"{h}.{{{','.join(tails)}}}")
    return "[" + ", ".join(parts) + "]"


class Trace:
    def __init__(self, enabled=True, verbose=False):
        self.enabled = enabled
        self.verbose = verbose
        self.rows: list = []

    def p(self, *a):
        if self.enabled:
            print(*a)

    def header(self, text):
        self.p(f"\n=== {text} ===")

    def plan(self, plan, waves_):
        self.header("PLAN (data)")
        by_id = {s.id: s for s in plan.steps}
        for i, w in enumerate(waves_):
            for sid in w:
                s = by_id[sid]
                dep = ",".join(f"{d}{'~' if d in s.soft else ''}" for d in s.depends_on) or "-"
                prm = f" params={s.params}" if s.params else ""
                self.p(f"  w{i} {s.id:<13} deps=[{dep}]{prm}  <- {s.why}")
        self.p("  (~ = soft dependency: step still runs, degraded, if that dependency fails)")
        for sk in plan.skipped:
            self.p(f"  SKIP {sk['agent']:<10} {sk['reason']}")
        for n in plan.notes:
            self.p(f"  note: {n}")

    def step(self, wave, r):
        self.rows.append(r)
        status = {"ok": "OK", "failed": "FAILED", "skipped": "SKIPPED", "degraded": "OK(degraded)"}[r["state"]]
        line = (f"[w{wave}] {r['id']:<13} {r['secs']:>4.1f}s  Rs{r['cost']:>5.2f}  {status:<12}"
                f" read={compress(r['reads'])} wrote={compress(r['writes'])} tools=[{r['tools']}]")
        self.p(line)
        for w in r.get("warnings", []):
            self.p(f"        ! {w}")
        if r.get("error"):
            self.p(f"        x {r['error']}")
        if self.verbose:
            for k, v in sorted(r.get("_writes", {}).items()):
                text = json.dumps(v, default=str, ensure_ascii=False)
                self.p(f"        > {k} = {text if len(text) <= 360 else text[:360] + ' ...(' + str(len(text)) + ' chars)'}")
            for n in r.get("_notes", []):
                self.p(f"        + memory: [{n['type']}/{n['topic']}] {n['text']}")

    def wave_end(self, wave, secs, seq_secs):
        self.p(f"      -- wave {wave} wall {secs:.1f}s (sequential would be {seq_secs:.1f}s)")

    def totals(self, meter, wall, seq):
        self.header("COST + TIME")
        for tool, d in meter.by_tool().items():
            c = f" (+{d['cached']} cache hits, free)" if d["cached"] else ""
            self.p(f"  {tool:<12} {d['calls']:>3} calls  Rs{d['cost']:>6.2f}{c}")
        self.p(f"  TOTAL SPENT: Rs {meter.total():.2f}   simulated wall time {wall:.1f}s (sequential {seq:.1f}s)")
