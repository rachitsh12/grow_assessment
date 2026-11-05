"""Mira: tailors the resume. Only real records and claimed skills WITH evidence; never invents jobs/degrees/certs."""
import json

from agents.common import cgpa_of, profile_skills, skill_gaps, skill_label, src

SPEC = {"reads": ["profile"], "optional_reads": ["research.job", "research.resumes", "memory.recall", "memory.brief"],
        "writes": ["resume"]}


async def run(ctx):
    profile = ctx.get("profile")
    job, peers = ctx.get("research.job"), ctx.get("research.resumes")
    have = profile_skills(profile)
    skills = [{"skill": skill_label(k), "level": v["level"], "evidence": v["evidence"]}
              for k, v in have.items() if v["evidence"]]
    unproven = [skill_label(k) for k, v in have.items() if not v["evidence"]]
    recs = {r["id"]: r for r in profile["records"]}
    projects = []
    for r in profile["records"]:
        if r["type"] in ("college_project", "extracurricular"):
            projects.append({"title": r["title"], "bullet": r["detail"].rstrip("."), "record": r["id"]})
    edu = profile["education"][0]
    education = f"{edu['degree']}, {edu['college']} ({edu['year']}), {edu['score']}"
    context = {"degree": edu["degree"], "year": edu["year"], "skills": sorted(s["skill"] for s in skills),
               "target": (job or {}).get("title", "data analyst role")}
    summary = ctx.tools.llm("mira summary", json.dumps(context, sort_keys=True), lambda: (
        f"{edu['degree']} graduate ({edu['year']}) with hands-on Excel analysis and SQL coursework, "
        f"looking for an entry-level {context['target']}."))
    gaps = []
    if not job:
        ctx.warn("no job post for this company: resume is generic and skill gaps cannot be computed")
    for g in skill_gaps(profile, job):
        gaps.append({**g, "why": f"{g['required_by']} is required by the job post" + (f" ({src(job)})" if job else ""),
                     "action": "learn and add only after you can show it"})
    certs = (peers or {}).get("certs", {})
    if certs:
        top = sorted(certs, key=certs.get, reverse=True)[0]
        gaps.append({"skill": "certification", "label": "Certification", "level": "none held",
                     "why": f"{certs[top]} of {peers['n']} placed resumes list '{top}'; you hold none (not added to the resume)",
                     "action": "earn one, then add it"})
    order = (peers or {}).get("section_order") or ["Education", "Skills", "Projects"]
    ctx.put("resume.sections", {"summary": summary, "skills": skills, "projects": projects, "education": education,
                                "certifications": []})
    ctx.put("resume.section_order", {"order": order, "source": [src(p) for p in (peers or {}).get("peers", [])[:3]]})
    ctx.put("resume.gaps", gaps)
    ctx.put("resume.not_added", {"skills_without_evidence": unproven})
    ctx.put("resume.memory_used", ctx.brief())
    # honesty guard: every listed skill must trace back to a real record
    assert all(s["evidence"] for s in skills) and all(p["record"] in recs for p in projects)
    if unproven:
        ctx.warn(f"left off the resume (no evidence in records): {', '.join(unproven)}")
    ctx.remember("fact", "resume_gaps", f"Mira: gaps for {context['target']}: " +
                 ", ".join(g["label"] for g in gaps), source="job post")
