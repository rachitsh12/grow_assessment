"""The four tools as stubs over demo_data.json. Every call is metered; nothing else is reachable.

fetch(url)        Rs 0.10  fails on needs_browser pages
browse(url)       Rs 5.00  reads anything
llm(prompt)       Rs 0.50  returns the canned text the agent passes in (stub)
sandbox.run(code) Rs 1.00  untrusted SQL: single SELECT, read-only authorizer, step budget

`catalog()` is a FREE metadata listing (url/type/company/date/flag/title, no content). It stands in for a
search index so we can drop junk pages before paying to read them. Assumption stated in DESIGN/README.
"""
import copy
import hashlib
import json
import re
import sqlite3

from tools import webfilter


class NeedsBrowser(Exception):
    pass


class PageNotFound(Exception):
    pass


class UnsafePrompt(Exception):
    pass


FIXTURE_SQL = """
CREATE TABLE employee(id INTEGER, name TEXT, salary INTEGER);
INSERT INTO employee VALUES (1,'A',100),(2,'B',200),(3,'C',300),(4,'D',300);
CREATE TABLE customers(id INTEGER, name TEXT);
INSERT INTO customers VALUES (1,'Asha'),(2,'Ravi'),(3,'Meena');
CREATE TABLE orders(id INTEGER, customer_id INTEGER, amount INTEGER);
INSERT INTO orders VALUES (1,1,500),(2,1,250);
"""
_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def run_sql_sandbox(code: str, max_ticks: int = 2000) -> dict:
    """Run untrusted SQL: one statement, SELECT/WITH only, authorizer denies everything but reads,
    in-memory DB, progress handler aborts runaway queries. (Not container isolation; see README.)"""
    q = code.strip().rstrip(";").strip()
    if ";" in q:
        return {"ok": False, "rows": [], "error": "multiple statements not allowed"}
    if not re.match(r"(?is)^(select|with)\b", q):
        return {"ok": False, "rows": [], "error": "only SELECT/WITH allowed"}
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(FIXTURE_SQL)
        conn.set_authorizer(lambda action, *a: sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY)
        ticks = {"n": 0}

        def _budget():
            ticks["n"] += 1
            return 1 if ticks["n"] > max_ticks else 0

        conn.set_progress_handler(_budget, 1000)
        rows = conn.execute(q).fetchmany(1000)
        return {"ok": True, "rows": [list(r) for r in rows], "error": None}
    except Exception as e:  # untrusted code may raise anything
        return {"ok": False, "rows": [], "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()


class World:
    """The 'internet' + caches. Shared across steps (and users in cohort mode)."""

    def __init__(self, data: dict):
        self.meta = data["meta"]
        self.costs = data["meta"]["tool_costs_rs"]
        self.times = data["meta"]["tool_times_s"]
        self.pages = {p["url"]: p for p in data["pages"]}
        self.page_cache: dict = {}
        self.sandbox_cache: dict = {}
        self.llm_cache: dict = {}      # llm output is a pure function of its prompt (temperature 0), so reuse it

    def companies(self):
        return sorted({p["company"] for p in self.pages.values() if p["company"]})


class Tools:
    """Per-step handle: charges the shared meter, remembers its own seconds/cost for the trace."""

    def __init__(self, world: World, meter, step_id: str):
        self.w, self.meter, self.step = world, meter, step_id
        self.secs = 0.0
        self.cost = 0.0
        self.counts: dict = {}
        self.cached: dict = {}

    def _charge(self, tool, note="", cached=False):
        cost = 0.0 if cached else self.w.costs[tool]
        secs = 0.0 if cached else self.w.times[tool]
        self.meter.add(self.step, tool, cost, secs, note, cached)
        self.cost += cost
        self.secs += secs
        bucket = self.cached if cached else self.counts
        bucket[tool] = bucket.get(tool, 0) + 1

    def catalog(self):
        return [{k: v for k, v in p.items() if k != "content"} for p in self.w.pages.values()]

    def fetch(self, url):
        page = self.w.pages.get(url)
        if page is None:
            raise PageNotFound(url)
        if page["needs_browser"]:
            self._charge("fetch", f"FAILED needs_browser {url}")
            raise NeedsBrowser(url)
        key = ("fetch", url)
        if key in self.w.page_cache:
            self._charge("fetch", url, cached=True)
            return copy.deepcopy(self.w.page_cache[key])
        self._charge("fetch", url)
        self.w.page_cache[key] = page
        return copy.deepcopy(page)

    def browse(self, url):
        page = self.w.pages.get(url)
        if page is None:
            raise PageNotFound(url)
        key = ("browse", url)
        if key in self.w.page_cache:
            self._charge("browse", url, cached=True)
            return copy.deepcopy(self.w.page_cache[key])
        self._charge("browse", url)
        self.w.page_cache[key] = page
        return copy.deepcopy(page)

    def llm(self, purpose: str, prompt: str, canned):
        """Stub: `canned` is what the model 'returns'. Prompts must be built from structured, screened data."""
        if webfilter.has_injection(prompt):
            raise UnsafePrompt(f"{purpose}: prompt contains instruction-like web text")
        key = hashlib.sha1(f"{purpose}\n{prompt}".encode()).hexdigest()
        if key in self.w.llm_cache:
            self._charge("llm", f"{purpose} (cache)", cached=True)
            return self.w.llm_cache[key]
        self._charge("llm", purpose)
        out = canned() if callable(canned) else canned
        self.w.llm_cache[key] = out
        return out

    def sandbox_run(self, code: str, label: str = ""):
        key = hashlib.sha1(re.sub(r"\s+", " ", code.strip().lower()).encode()).hexdigest()
        if key in self.w.sandbox_cache:
            self._charge("sandbox.run", f"{label} (cache)", cached=True)
            return copy.deepcopy(self.w.sandbox_cache[key])
        self._charge("sandbox.run", label)
        res = run_sql_sandbox(code)
        self.w.sandbox_cache[key] = res
        return copy.deepcopy(res)

    def summary(self) -> str:
        parts = [f"{t} x{n}" for t, n in self.counts.items()]
        parts += [f"{t} x{n} cached" for t, n in self.cached.items()]
        return ", ".join(parts) if parts else "-"
