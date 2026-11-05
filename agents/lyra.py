"""Lyra: learning plan. importance = 0.5*gap + 0.3*asked_frac + 0.2*required; scheduled greedily into the
hours available before the interview (days_left x HOURS_PER_DAY, both stated assumptions). The rest is 'deferred'."""
from agents.common import anxious_about_timers, cite, find_topic, own_words_for

SPEC = {"reads": ["research.job", "research.interviews"],
        "optional_reads": ["resume.gaps", "test.results", "research.resumes", "research.test_format", "memory.recall", "memory.brief"],
        "writes": ["lyra"]}

HOURS_PER_DAY = 1.5


def frac(iv, topics):
    n = max(iv["n"], 1)
    return max([(find_topic(iv, "tech", t) or {"count": 0})["count"] / n for t in topics] + [0])


async def run(ctx):
    job, iv = ctx.get("research.job"), ctx.get("research.interviews")
    tf = ctx.get("research.test_format") or {}
    results, gaps_in = ctx.get("test.results"), ctx.get("resume.gaps")
    peers, recall = ctx.get("research.resumes") or {}, ctx.get("memory.recall", {})
    days = ctx.config.days_left
    cap = days * HOURS_PER_DAY
    gap_keys = {g["skill"] for g in gaps_in} if gaps_in is not None else None
    if gaps_in is None:
        ctx.warn("no Mira gap list: deriving gaps from the job post directly")
    measured = {r["topic"]: r["score"] for r in (results or [])}
    sql_gap = 1 - measured.get("sql:joins", 0.5)            # no test -> assume basic (0.5) from coursework
    items = []

    def add(topic, resource, hours, why, gap, asked, required, cites=None):
        imp = round(0.5 * gap + 0.3 * asked + 0.2 * required, 2)
        items.append({"topic": topic, "resource": resource, "duration_h": hours, "why": why,
                      "importance": imp, "evidence": cites or []})

    add("SQL: LEFT JOIN and 'customers without orders'",
        "5 self-written anti-join queries on practice tables, then explain each aloud", 3,
        f"joins score {round((1 - sql_gap) * 100)}%; INNER vs LEFT JOIN is a repeat Infosys question",
        sql_gap, frac(iv, ["inner_vs_left_join"]), 1, [cite(iv, "tech", "inner_vs_left_join")])
    add("SQL: second / Nth highest salary variants", "dense_rank and the no-LIMIT version, 6 practice queries", 1.5,
        "asked most often in the reports", 0.2, frac(iv, ["second_highest_salary"]), 1, [cite(iv, "tech", "second_highest_salary")])
    add("Excel: pivot tables, XLOOKUP, SUMIFS", "redo your store-sales workbook with XLOOKUP and a SUMIFS check", 2,
        "pivot / lookup questions appear in the reports; you already have pivot experience", 0.4,
        frac(iv, ["pivot_table", "excel_lookup", "sumifs"]), 1, [cite(iv, "tech", "pivot_table")])
    add("Dashboard story (Power BI)", "build a 5-KPI Power BI dashboard from your own store-sales data, then explain the decision it supports", 6,
        "Power BI is required and 'explain a dashboard you built' is asked; you have no dashboard yet",
        1.0 if (gap_keys is None or "power bi" in gap_keys) else 0.2, frac(iv, ["dashboard_story"]), 1,
        [cite(iv, "tech", "dashboard_story")])
    pyg = 1.0 if (gap_keys is None or "python" in gap_keys) else 0.2
    add("Python basics (pandas)", "load a CSV, filter, group-by, plot; redo the store analysis", 4,
        "'basic Python' is in the job post", pyg, 0, 1, [])
    certs = peers.get("certs", {})
    if certs:
        top = max(certs, key=certs.get)
        add(f"Certification: {top}", f"{top} (self-paced)", 10, f"{certs[top]} of {peers['n']} placed resumes list it; optional",
            1.0, 0, 0, [f"{certs[top]} of {peers['n']} placed resumes"])
    if anxious_about_timers(recall):
        q = own_words_for(recall, "timed_tests")
        add("Timed-test practice", "2 full mock tests: first untimed, second with the timer", 3.5,
            f"you said \"{q}\"; the online test is {tf.get('minutes', 100)} minutes with a strict timer",
            0.8, 0.5, 1, [])
    items.sort(key=lambda i: -i["importance"])
    plan, deferred, used = [], [], 0.0
    for i in items:
        if used + i["duration_h"] <= cap:
            plan.append(i)
            used += i["duration_h"]
        else:
            deferred.append(i)
    ctx.put("lyra.plan", plan)
    ctx.put("lyra.deferred", deferred)
    ctx.put("lyra.capacity", {"days_left": days, "hours_per_day": HOURS_PER_DAY, "hours_used": used, "hours_total": cap,
                              "assumption": "interview date is not in the data; days_left is assumed"})
    ctx.put("lyra.memory_used", ctx.brief())
    ctx.remember("fact", "learning_plan", "Lyra: plan: " + "; ".join(i["topic"] for i in plan[:4]), source=f"{days} days left")
