"""Cost meter: every tool call is recorded with step, cost and simulated seconds."""
from dataclasses import dataclass


@dataclass
class Entry:
    step: str
    tool: str
    cost: float
    secs: float
    note: str = ""
    cached: bool = False


class CostMeter:
    def __init__(self):
        self.entries: list[Entry] = []

    def add(self, step, tool, cost, secs, note="", cached=False):
        self.entries.append(Entry(step, tool, cost, secs, note, cached))

    def total(self) -> float:
        return round(sum(e.cost for e in self.entries), 2)

    def by_tool(self) -> dict:
        out: dict[str, dict] = {}
        for e in self.entries:
            d = out.setdefault(e.tool, {"calls": 0, "cached": 0, "cost": 0.0})
            if e.cached:
                d["cached"] += 1
            else:
                d["calls"] += 1
            d["cost"] = round(d["cost"] + e.cost, 2)
        return out

    def calls(self, tool: str, include_cached=False) -> int:
        return sum(1 for e in self.entries if e.tool == tool and (include_cached or not e.cached))

    def extend(self, other: "CostMeter"):
        self.entries.extend(other.entries)
