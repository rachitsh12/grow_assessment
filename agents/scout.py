"""Scout: finds and ranks jobs. It only DRAFTS an application; applying needs the approval gate."""
from agents.common import cgpa_of, profile_skills, skill_label, src

SPEC = {"reads": ["goal", "profile", "research.job"], "optional_reads": ["research.rejected"],
        "writes": ["scout", "actions.scout"]}


async def run(ctx):
    goal, profile, job = ctx.get("goal"), ctx.get("profile"), ctx.get("research.job")
    rejected = [r for r in (ctx.get("research.rejected") or []) if r.get("type") == "job_post"]
    if not job:
        ctx.put("scout.jobs", [])
        ctx.put("scout.rejected", rejected)
        ctx.warn("no matching job found")
        return
    have = profile_skills(profile)
    sk = [have.get(s["key"], {"strength": 0.0})["strength"] for s in job["skills"]]
    skill_fit = sum(sk) / len(sk) if sk else 0.0
    cgpa = cgpa_of(profile)
    year = profile["education"][0]["year"]
    eligible = cgpa >= (job["min_cgpa"] or 0) and year in job["grad_years"]
    city_ok = goal["city"].lower() == (job["location"] or "").lower()
    fit = round(100 * (0.5 * skill_fit + 0.3 * eligible + 0.2 * city_ok))
    gaps = [skill_label(s["key"]) for s, v in zip(job["skills"], sk) if v < 0.6]
    ctx.put("scout.jobs", [{
        "company": job["company"], "title": job["title"], "location": job["location"], "fit_score": fit,
        "link": job["url"],
        "why": [f"eligible: {cgpa} CGPA vs {job['min_cgpa']} minimum, class of {year}" if eligible else
                f"NOT eligible: needs {job['min_cgpa']} CGPA and class of {job['grad_years']}",
                f"skills evidenced {round(skill_fit * 100)}%; weak: {', '.join(gaps) or 'none'}",
                f"source: {src(job)}"]}])
    ctx.put("scout.rejected", rejected)
    ctx.put("actions.scout", {"type": "apply", "job_url": job["url"], "status": "pending_approval",
                              "payload": "tailored resume (Mira) + profile", "created": str(ctx.today)})
    ctx.remember("fact", "job_fit", f"Scout: {job['title']} fit {fit}%; eligible={eligible}", source=job["url"])
