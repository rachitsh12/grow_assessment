"""Vera: technical mock interview. Questions come from what Infosys actually asked (with source + date),
ordered by Priya's weak spots first. Scoring individual live answers needs the user to reply (not in demo data);
here Vera reports readiness per topic from Sage's measured scores, or from claim-vs-evidence if Sage is down."""
import json

from agents.common import anxious_about_timers, claim_gap, cite, own_words_for, src

SPEC = {"reads": ["goal", "profile", "research.interviews"],
        "optional_reads": ["test.results", "research.tips", "memory.recall", "memory.brief"], "writes": ["vera"]}

WEAK_MAP = {"sql:joins": ["inner_vs_left_join", "customers_without_orders"], "sql:second_highest": ["second_highest_salary"]}
N_QUESTIONS = 6


async def run(ctx):
    profile, iv = ctx.get("profile"), ctx.get("research.interviews")
    results, recall = ctx.get("test.results"), ctx.get("memory.recall", {})
    tips = ctx.get("research.tips") or []
    weak = set()
    if results:
        basis = "measured by Sage"
        for r in results:
            if r["score"] < 0.6:
                weak.update(WEAK_MAP.get(r["topic"], []))
    else:
        basis = "claim vs records (no test scores available)"
        ctx.warn("no test scores: estimating readiness from records, not measurement")
        if claim_gap(recall, None, profile):
            weak.update(d["topic"] for d in iv["tech"] if d["subject"] == "sql")
    pool = [d for d in iv["tech"] if d["subject"] != "other"]
    pool.sort(key=lambda d: (d["topic"] not in weak, -d["count"], -int(d["latest"].replace("-", ""))))
    seen_q, uniq = set(), []
    for d in pool:                                            # one question can map to two topics (pivot + SUMIFS)
        if d["example"] not in seen_q:
            seen_q.add(d["example"])
            uniq.append(d)
    pool = uniq
    qs = []
    for d in pool[:N_QUESTIONS]:
        qs.append({"question": d["example"], "topic": d["topic"], "why_asked": cite(iv, "tech", d["topic"]),
                   "focus": d["topic"] in weak})
    readiness = {}
    for d in pool[:N_QUESTIONS]:
        if d["topic"] in weak:
            readiness[d["topic"]] = 0.4
        elif d["subject"] == "sql":
            readiness[d["topic"]] = 0.7 if results else 0.5
    anxious = anxious_about_timers(recall)
    tip = next((t for t in tips if "out loud" in t["text"].lower()), None)
    feedback = ctx.tools.llm("vera feedback", json.dumps(
        {"weak": sorted(weak), "anxious": anxious, "basis": basis, "focus": ctx.params.get("focus")}, sort_keys=True),
        lambda: ("Start with the weak topics: " + ", ".join(sorted(weak)) + ". " if weak else "") +
        "Explain each query out loud before typing it." +
        (" Do the first round untimed, then add the timer." if anxious else ""))
    ctx.put("vera.questions", qs)
    ctx.put("vera.readiness", {"basis": basis, "topics": readiness})
    ctx.put("vera.feedback", feedback)
    ctx.put("vera.tip", {**tip, "source": src(tip)} if tip else None)
    ctx.put("vera.memory_used", ctx.brief())
    quote = own_words_for(recall, "timed_tests")
    if quote:
        ctx.remember("coaching", "timed_tests", f"Vera: untimed first round because user said \"{quote}\"", source="own words")
    if weak:
        ctx.remember("coaching", "weak_topics", f"Vera: drilling {', '.join(sorted(weak))} first", source=basis)
