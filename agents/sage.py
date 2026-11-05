"""Sage: builds the test and grades the user's coding answers in the sandbox (the only untrusted code).

Grading truth = running the user's code against fixture tables and comparing to a trusted reference result.
The `note` field in the demo data is NOT used (it is a label for us, not evidence). Reference answers are
trusted and precomputed in-process for free; only the untrusted code costs a sandbox.run.
Rubric: right rows 1.0 | valid query but wrong rows 0.4 | error 0.0.
"""
import json

from agents.common import anxious_about_timers, cite, own_words_for
from tools.tools import run_sql_sandbox

SPEC = {"reads": ["goal", "profile", "research.interviews", "research.test_format"],
        "optional_reads": ["research.job", "memory.recall", "memory.brief"], "writes": ["test"]}

QUESTIONS = {
    "q_second_highest_salary": {
        "topic": "sql:second_highest", "label": "SQL second-highest-salary", "interview_topic": "second_highest_salary",
        "text": "Find the second highest salary from the employee table.",
        "ref": "SELECT MAX(salary) FROM employee WHERE salary < (SELECT MAX(salary) FROM employee)"},
    "q_customers_without_orders": {
        "topic": "sql:joins", "label": "SQL joins", "interview_topic": "inner_vs_left_join",
        "text": "List the customers who never placed an order.",
        "ref": "SELECT c.name FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE o.id IS NULL"},
}


def pct(x):
    return f"{round(x * 100)}%"


async def run(ctx):
    profile, iv, tf = ctx.get("profile"), ctx.get("research.interviews"), ctx.get("research.test_format")
    recall = ctx.get("memory.recall", {})
    anxious = anxious_about_timers(recall)
    minutes = (tf or {}).get("minutes") or 100

    aptitude = [{"topic": s, "text": f"{s.title()} practice set (item bank is a stub)"}
                for s in (tf or {}).get("sections", []) if s != "sql"]
    sql_qs, results, not_graded = [], [], []
    answers = {a["question_id"]: a for a in profile.get("coding_answers", [])}
    for qid, q in QUESTIONS.items():
        why = cite(iv, "tech", q["interview_topic"])
        if q["topic"] == "sql:joins" and why:
            why = "practical form of INNER vs LEFT JOIN: " + why
        sql_qs.append({"id": qid, "text": q["text"], "why_asked": why or "no fetched report asks this directly"})
        a = answers.get(qid)
        if not a:
            not_graded.append(f"{q['label']}: no answer submitted")
            continue
        res = ctx.tools.sandbox_run(a["code"], label=qid)          # untrusted code -> sandbox only
        expected = run_sql_sandbox(q["ref"])["rows"]               # trusted reference, free
        if not res["ok"]:
            score, detail = 0.0, f"query failed: {res['error']}"
        elif sorted(res["rows"]) == sorted(expected):
            score, detail = 1.0, "correct result"
        else:
            score, detail = 0.4, f"valid query but returned {res['rows']} instead of {expected}"
            if "inner join" in a["code"].lower() and "left join" in q["ref"].lower():
                detail += " (INNER JOIN drops customers with no orders; use LEFT JOIN ... WHERE o.id IS NULL)"
        results.append({"topic": q["topic"], "label": q["label"], "score": score, "detail": detail, "question": qid})
        ctx.remember("score", q["topic"], f"Sage: {q['label']} {pct(score)}", source=qid, value=score)
    excel = [{"topic": d["topic"], "text": d["example"], "why_asked": cite(iv, "tech", d["topic"])}
             for d in iv["tech"] if d["subject"] == "excel"][:2]
    not_graded.append("aptitude and Excel sections: item bank is a stub, no answers in the data")

    mode = "untimed first attempt, then timed" if anxious else "timed"
    sections = [{"section": "aptitude", "questions": aptitude, "time_limit_min": None},
                {"section": "sql_coding", "questions": sql_qs, "time_limit_min": None},
                {"section": "excel", "questions": excel, "time_limit_min": None}]
    feedback = ctx.tools.llm("sage feedback", json.dumps({"results": results, "anxious": anxious}, sort_keys=True),
                             lambda: " ".join(f"{r['label']}: {pct(r['score'])} - {r['detail']}." for r in results)
                             + (" Attempt untimed first, then add the timer." if anxious else ""))
    ctx.put("test.sections", sections)
    ctx.put("test.results", results)
    ctx.put("test.meta", {"time_limit_min": minutes, "mode": mode, "not_graded": not_graded,
                          "time_source": (tf or {}).get("sources", [])[:1]})
    ctx.put("test.feedback", feedback)
    ctx.put("test.memory_used", ctx.brief())
    quote = own_words_for(recall, "timed_tests")
    if quote:
        ctx.remember("coaching", "timed_tests", f"Sage: test mode '{mode}' because user said \"{quote}\"",
                     source="own words")
