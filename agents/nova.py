"""Nova: drafts one LinkedIn post in Priya's voice from REAL milestones. Never posts; the draft waits for approval."""
import json
from datetime import timedelta

from agents.common import own_words_for, src

SPEC = {"reads": ["profile"], "optional_reads": ["research.news", "test.results", "memory.recall", "memory.brief",
                                                  "actions.nova"], "writes": ["nova", "actions.nova"]}


def next_tuesday(d):
    return d + timedelta(days=(1 - d.weekday()) % 7 or 7)


async def run(ctx):
    profile, news = ctx.get("profile"), ctx.get("research.news") or []
    results, recall = ctx.get("test.results"), ctx.get("memory.recall", {})
    proj = next(r for r in profile["records"] if r["type"] == "college_project")
    clause = proj["detail"].split(";")[0].rstrip(".")
    liked = own_words_for(recall, "sales_data_analysis")
    joins = next((r["score"] for r in (results or []) if r["topic"] == "sql:joins"), None)
    next_up = "LEFT JOIN is my current focus" if joins is not None and joins < 0.6 else "next up: SQL JOINs"
    voice = [p["text"] for p in profile.get("past_posts", [])]
    payload = {"project": proj["title"], "clause": clause, "liked": liked, "next_up": next_up, "voice": voice}
    text = ctx.tools.llm("nova draft", json.dumps(payload, sort_keys=True), lambda:
        f"Something I enjoyed: {proj['title'].lower()}. {clause}. " + (liked + " " if liked else "") +
        f"Now practising SQL ({next_up}). Looking for data analyst roles in Bangalore. #DataAnalytics #Excel #SQL")
    hook = news[0] if news else None
    when = next_tuesday(ctx.today)
    draft = {"text": text, "topic": "learning in public: store-sales project + SQL practice",
             "suggested_time": f"{when} 09:30 IST (Tuesday morning)",
             "why_now": f"Infosys announced fresher hiring in data roles ({src(hook)})" if hook else "no company news available",
             "voice": "short, first person, plain words (matches your past posts)",
             "honesty": "only real milestones; no skill claimed beyond your records"}
    ctx.put("nova.draft", draft)
    ctx.put("nova.memory_used", ctx.brief())
    ctx.put("actions.nova", {"type": "post", "status": "pending_approval", "text": text,
                             "suggested_time": draft["suggested_time"], "created": str(ctx.today)})
    ctx.remember("fact", "linkedin_draft", f"Nova: drafted a post about {proj['title']}; awaiting approval", source="draft")
