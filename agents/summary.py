"""grace_summary: collects every agent's result into ONE card. Also usable without an llm as a fallback card
(main.py calls build_card directly if this step itself fails)."""
import json

from agents.common import claim_gap

SPEC = {"reads": ["goal"],
        "optional_reads": ["scout", "resume", "test", "vera", "kai", "lyra", "nova", "actions", "approvals",
                           "research", "run.status", "memory.recall"], "writes": ["card"]}


def state_getter(state):
    def get(key, default=None):
        if key in state.data:
            return state.data[key]
        sub = {k[len(key) + 1:]: v for k, v in state.data.items() if k.startswith(key + ".")}
        return sub or default
    return get


def build_card(get, headline=None):
    goal = get("goal")
    jobs_raw = get("scout.jobs")                      # None = Scout was not part of this plan
    jobs = jobs_raw or []
    results = get("test.results") or []
    status = get("run.status") or {}
    approvals = get("approvals") or {}
    actions = get("actions") or {}
    plan = get("lyra.plan") or []
    vera_q, kai_q = get("vera.questions") or [], get("kai.questions") or []
    res = get("resume.sections")
    notes = []
    for g in claim_gap(get("memory.recall", {}), results, {"records": [], "skills_claimed": []}):
        notes.append(f"You said \"{g['claim']}\"; measured {g['measured_topic']} = {round(g['measured'] * 100)}%. Planning on the measurement.")
    sk = get("research.skipped_browse") or []
    if sk:
        notes.append(f"Skipped {len(sk)} browser-only report(s), saving Rs {sum(s['saved_rs'] for s in sk):.0f}; "
                     f"they may hold newer questions ({', '.join(s['date'] for s in sk)}).")
    rej = get("research.rejected") or []
    unsafe = [r for r in rej if r["stage"] == "content" or "scam" in r["reason"] or "domain" in r["reason"]]
    if unsafe:
        notes.append(f"Rejected {len(unsafe)} untrustworthy page(s): " + "; ".join(f"{r['reason']}" for r in unsafe))
    san = get("research.sanitized") or []
    if san:
        notes.append(f"Stripped hidden instructions from {len(san)} page(s); page text is treated as data only.")
    conf = get("research.confidence")
    if conf and conf != "high":
        notes.append(f"Research confidence is {conf}: {(get('research.interviews') or {}).get('n', 0)} usable report(s)"
                     + ("" if get("research.job") else ", no official job post found") + ".")
    degraded = {}
    for v in status.values():
        for w in v["warnings"]:
            if w.startswith("degraded"):
                degraded.setdefault(v["agent"], []).append(w.replace("degraded: ran without ", ""))
    return {
        "headline": headline or "Partial plan (summary step unavailable)",
        "goal": goal, "jobs": jobs_raw, "tailored": bool(get("research.job")),
        "resume": ({"order_source": get("resume.section_order"), "summary": res["summary"], "skills": [s["skill"] for s in res["skills"]],
                    "gaps": [g["label"] for g in (get("resume.gaps") or [])]} if res else None),
        "practice_test": ({"sections": [s["section"] for s in (get("test.sections") or [])],
                           "limit_min": (get("test.meta") or {}).get("time_limit_min"),
                           "mode": (get("test.meta") or {}).get("mode"),
                           "questions": [{"q": q["text"], "why": q["why_asked"]} for sec in (get("test.sections") or [])
                                         if sec["section"] == "sql_coding" for q in sec["questions"]],
                           "graded": [f"{r['label']} {round(r['score'] * 100)}%" for r in results]} if (get("test.sections")) else None),
        "interview_prep": {"technical": [{"q": q["question"], "why": q["why_asked"], "focus": q["focus"]} for q in vera_q],
                           "hr": [{"q": q["question"], "why": q["why_asked"]} for q in kai_q]},
        "learning_plan": [{"topic": i["topic"], "hours": i["duration_h"], "why": i["why"], "evidence": [e for e in i["evidence"] if e]} for i in plan],
        "linkedin_draft": get("nova.draft"),
        "needs_your_ok": [f"{who}: {a['type']} ({approvals.get(who, {}).get('status', a['status'])})"
                          for who, a in sorted(actions.items())
                          if approvals.get(who, {}).get("status", a["status"]) == "pending_approval"],
        "done": [f"{who}: {approvals[who]['status']}" for who in sorted(approvals) if approvals[who]["status"] in ("applied", "posted")],
        "not_completed": [{"agent": v["agent"], "why": v["error"]} for v in status.values() if v["state"] in ("failed", "skipped")],
        "degraded": [{"agent": a, "note": "ran without " + ", ".join(sorted(set(m)))} for a, m in degraded.items()],
        "notes": notes,
    }


async def run(ctx):
    jobs = ctx.get("scout.jobs") or []
    card = build_card(ctx.get)
    summary_in = {"jobs": len(jobs), "plan": len(card["learning_plan"]), "pending": card["needs_your_ok"],
                  "missing": [m["agent"] for m in card["not_completed"]]}
    have = [x for x, ok in (("a tailored resume" if card["tailored"] else "a generic resume (no job post found)", card["resume"]), ("a practice test", card["practice_test"]),
                            ("interview prep", card["interview_prep"]["technical"] or card["interview_prep"]["hr"]),
                            ("a learning plan", card["learning_plan"])) if ok]
    card["headline"] = ctx.tools.llm("grace summary", json.dumps({**summary_in, "have": have}, sort_keys=True), lambda:
        ((f"{len(jobs)} job match" if jobs else "No matching job found") + (", " if have else "")
         if card["jobs"] is not None else "") + ", ".join(have) + " ready."
        + (f" Waiting for your OK: {', '.join(card['needs_your_ok'])}." if card["needs_your_ok"] else "")
        + (f" Could not complete: {', '.join(summary_in['missing'])}." if summary_in["missing"] else ""))
    ctx.put("card", card)
    ctx.remember("fact", "session_summary", f"Grace: day {ctx.config.day} card: "
                 + (f"{len(jobs)} job, " if card["jobs"] is not None else "") + f"{len(card['learning_plan'])} learning items; "
                 + (f"waiting for OK: {', '.join(card['needs_your_ok'])}" if card["needs_your_ok"] else "nothing waiting")
                 + (f"; missing: {', '.join(summary_in['missing'])}" if summary_in["missing"] else ""), source="summary")


def render_card(card, out=print):
    p = out
    p(f"\n=== SUMMARY CARD (Grace) ===")
    p(f"  {card['headline']}")
    for j in card["jobs"] or []:
        p(f"  JOB     {j['company']} - {j['title']} ({j['location']}) fit {j['fit_score']}%  {j['link']}")
        for w in j["why"]:
            p(f"            - {w}")
    if card["jobs"] == []:
        p("  JOB     none found")
    r = card["resume"]
    if r:
        p(f"  RESUME  {r['summary']}")
        if r["order_source"]:
            p(f"            section order {' > '.join(r['order_source']['order'])}  [placed resumes: {'; '.join(r['order_source']['source'])}]")
        p(f"            skills (evidenced only): {', '.join(r['skills'])};  gaps: {', '.join(r['gaps']) or 'none'}")
    t = card["practice_test"]
    if t:
        p(f"  TEST    {', '.join(t['sections'])}; {t['limit_min']} min, {t['mode']}; graded: {', '.join(t['graded']) or 'none'}")
        for q in t["questions"]:
            p(f"            - {q['q']}  [{q['why']}]")
    ip = card["interview_prep"]
    if ip["technical"]:
        p(f"  VERA    {len(ip['technical'])} technical questions (weak topics first):")
        for q in ip["technical"]:
            p(f"            {'*' if q['focus'] else '-'} {q['q']}  [{q['why']}]")
    if ip["hr"]:
        p(f"  KAI     {len(ip['hr'])} HR questions:")
        for q in ip["hr"]:
            p(f"            - {q['q']}  [{q['why']}]")
    if card["learning_plan"]:
        p("  LYRA    learning plan:")
        for i in card["learning_plan"]:
            p(f"            - {i['topic']} ({i['hours']}h): {i['why']}" + (f"  [{i['evidence'][0]}]" if i["evidence"] else ""))
    d = card["linkedin_draft"]
    if d:
        p(f"  NOVA    draft for {d['suggested_time']}: \"{d['text']}\"")
    for x in card["needs_your_ok"]:
        p(f"  OK?     {x}  -> nothing is sent until you approve (--approve)")
    for x in card["done"]:
        p(f"  DONE    {x}")
    for x in card["not_completed"]:
        p(f"  MISSING {x['agent']}: {x['why']}")
    for x in card["degraded"]:
        p(f"  DEGRADED {x['agent']}: {x['note']}")
    for n in card["notes"]:
        p(f"  NOTE    {n}")
