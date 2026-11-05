"""Shared state + per-step context that enforces declared reads/writes.

State is a flat dict with dotted, namespaced keys ("research.job", "test.results").
A declared prefix "research" covers "research" and every "research.*" key.
"""
import copy


class UndeclaredAccess(Exception):
    pass


def matches(key: str, prefix: str) -> bool:
    return key == prefix or key.startswith(prefix + ".")


def overlaps(a: str, b: str) -> bool:
    return matches(a, b) or matches(b, a)


class State:
    def __init__(self, initial: dict | None = None):
        self.data: dict = dict(initial or {})

    def keys(self):
        return list(self.data.keys())

    def commit(self, writes: dict):
        self.data.update(writes)

    def has_prefix(self, prefix: str) -> bool:
        return any(matches(k, prefix) for k in self.data)


class Ctx:
    """What one agent step sees. Reads come from a snapshot, writes are buffered."""

    def __init__(self, step, spec, state: State, tools, config, user_id, today, degraded):
        self.step = step
        self.spec = spec
        self._state = state
        self.tools = tools
        self.config = config
        self.user_id = user_id
        self.today = today
        self.degraded = list(degraded)          # soft dependencies that failed or were skipped
        self.params = dict(step.params)
        self._reads = list(spec["reads"]) + list(spec.get("optional_reads", []))
        self._writes = list(spec["writes"])
        self.read_log: set[str] = set()
        self.writes: dict = {}
        self.notes: list[dict] = []             # memory notes, committed only on success
        self.warnings: list[str] = []           # shown in the trace

    # ---- state access -------------------------------------------------
    def get(self, key, default=None):
        if not any(matches(key, p) for p in self._reads):
            raise UndeclaredAccess(f"{self.step.agent} read undeclared key '{key}'")
        self.read_log.add(key)
        data = self._state.data
        if key in data:
            return copy.deepcopy(data[key])
        sub = {k[len(key) + 1:]: copy.deepcopy(v) for k, v in data.items() if k.startswith(key + ".")}
        return sub or default

    def put(self, key, value):
        if not any(matches(key, p) for p in self._writes):
            raise UndeclaredAccess(f"{self.step.agent} wrote undeclared key '{key}'")
        self.writes[key] = value

    # ---- memory write-back -------------------------------------------
    def remember(self, type_, topic, text, source="", value=None, polarity=None):
        self.notes.append({"agent": self.step.agent, "type": type_, "topic": topic, "text": text,
                           "source": source, "value": value, "polarity": polarity})

    def warn(self, msg):
        self.warnings.append(msg)

    def brief(self):
        """Short 'what do we know about this user' lines for this agent (from Memory.summary_for)."""
        return (self.get("memory.brief", {}) or {}).get(self.step.agent, [])
