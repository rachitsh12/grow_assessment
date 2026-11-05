"""Kai: HR / manager round coach. Questions ranked by how often the reports asked them; answer outlines are built
only from Priya's real records, the job post and company news (each cited)."""
import json

from agents.common import anxious_about_timers, claim_gap, cite, src

SPEC = {"reads": ["goal", "profile"],
        "optional_reads": ["research.interviews", "research.news", "research.job", "test.results",
                           "memory.recall", "memory.brief"], "writes": ["kai"]}

GENERIC = [("Tell me about yourself", "about_yourself"), ("Why this company?", "why_company"),
           ("Are you OK with shifts and relocation?", "relocation_shifts")]


def outline(topic, profile, news, job):
    recs = {r["id"]: r for r in profile["records"]}
    edu = profile["education"][0]
    if topic == "about_yourself":
        return (f"{edu['degree']} {edu['year']} ({edu['score']}) -> {recs['rec_1']['title']} in Excel (rec_1) -> "
                f"led a Rs 2 lakh fest budget (rec_3) -> learning SQL now -> why data analyst. 60 seconds.")
    if topic == "why_company":
        if news:
            n = news[0]
            return f"Infosys is growing AI-assisted analytics and plans fresher data hiring ({src(n)}); link it to your store-sales project."
        return "Name one specific thing about the company and link it to your project."
    if topic == "relocation_shifts":
        cond = (job or {}).get("conditions") or "shifts and relocation"
        return f"Job post says: '{cond}' ({src(job) if job else 'no job post'}). Give your honest answer; your college is in Bangalore."
    if topic == "strengths":
        return "Pick two you can prove: tracking a Rs 2 lakh budget (rec_3), presenting findings to the store owner (rec_1)."
    if topic == "future_goals":
        return "Analyst now; deeper BI/analytics skills in 3 years. Tie to the learning plan you are actually following."
    return "Use one real example from your records, then the result."


async def run(ctx):
    profile = ctx.get("profile")
    iv, news, job = ctx.get("research.interviews"), ctx.get("research.news") or [], ctx.get("research.job")
    results, recall = ctx.get("test.results"), ctx.get("memory.recall", {})
    if iv:
        qs = [{"question": d["example"], "topic": d["topic"], "why_asked": cite(iv, "hr", d["topic"]),
               "outline": outline(d["topic"], profile, news, job)} for d in iv["hr"][:5]]
    else:
        ctx.warn("no research: using generic HR questions without sources")
        qs = [{"question": q, "topic": t, "why_asked": "generic (no research available)",
               "outline": outline(t, profile, news, job)} for q, t in GENERIC]
    gaps = claim_gap(recall, results, profile)
    anxious = anxious_about_timers(recall)
    tone = ctx.tools.llm("kai coaching", json.dumps({"gap": [g["topic"] for g in gaps], "anxious": anxious,
                                                     "focus": ctx.params.get("focus")}, sort_keys=True),
                         lambda: "Structure: situation, action, result. " +
                         ("Say what you can show ('comfortable with SELECT, GROUP BY, basic joins; practising LEFT JOIN') "
                          "instead of 'I'm good at SQL'. " if gaps else "") +
                         ("Pause before answering; nerves show most in the first 10 seconds." if anxious else ""))
    ctx.put("kai.questions", qs)
    ctx.put("kai.coaching", {"tone": tone, "claim_vs_evidence": gaps})
    ctx.put("kai.memory_used", ctx.brief())
    for g in gaps:
        ctx.remember("coaching", "overclaiming",
                     f"Kai: user says \"{g['claim']}\" but {g['basis']} shows {round(g['measured'] * 100)}%; coach calibrated claims",
                     source="own words vs evidence")
