"""Research: the ONLY agent that touches the web. Everyone else reads research.* from shared state.

Cost logic
- catalog() (free metadata) + trust filter drop wrong-company, scam, stale and lookalike pages BEFORE paying to read.
- fetch (Rs 0.10) for everything fetchable; browse (Rs 5) only if fewer than MIN_REPORTS usable reports.
- every fact keeps its source {url, date}.
"""
import re
from collections import Counter

from agents.common import skill_key
from tools import webfilter

SPEC = {"reads": ["goal"], "optional_reads": [], "writes": ["research"]}

MIN_REPORTS = 3
MAX_RESUMES = 3
MAX_NEWS = 2

TECH_RULES = [
    (r"second highest|nth highest", "second_highest_salary", "sql"),
    (r"inner join.*left join|left join", "inner_vs_left_join", "sql"),
    (r"without orders|never placed", "customers_without_orders", "sql"),
    (r"normali[sz]ation", "normalization", "sql"),
    (r"primary key", "primary_vs_foreign_key", "sql"),
    (r"\bcte\b", "cte", "sql"),
    (r"what is a join", "join_basics", "sql"),
    (r"group by", "group_by", "sql"),
    (r"where.*having", "where_vs_having", "sql"),
    (r"vlookup|xlookup", "excel_lookup", "excel"),
    (r"pivot", "pivot_table", "excel"),
    (r"sumifs", "sumifs", "excel"),
    (r"clean .*data", "excel_cleaning", "excel"),
    (r"macro", "excel_macro", "excel"),
    (r"dashboard", "dashboard_story", "bi"),
]
HR_RULES = [
    (r"tell me about yourself", "about_yourself", "hr"),
    (r"why (infosys|tcs)", "why_company", "hr"),
    (r"relocat|any location|shifts", "relocation_shifts", "hr"),
    (r"strengths", "strengths", "hr"),
    (r"3 years", "future_goals", "hr"),
]


def _slug(q):
    return re.sub(r"\W+", "_", q.lower()).strip("_")[:30]


def classify(q, rules):
    hits = [(t, s) for rx, t, s in rules if re.search(rx, q, re.I)]
    return hits or [(_slug(q), "other")]


def split_top(text):
    """Split on commas that are not inside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_report(p):
    c = p["content"]
    tech_part = c.split("HR:")[0]
    tech = [q.strip().rstrip(".").strip()
            for q in re.findall(r"\b\d\)\s*(.+?)(?=\s+\d\)\s|$)", tech_part, re.S)]
    hr_part = re.search(r"HR:\s*(.*?)(?:Result:|$)", c, re.S)
    hr = [s.strip() for s in re.split(r"(?<=[.?!])\s+", hr_part.group(1).strip()) if s.strip()] if hr_part else []
    res = re.search(r"Result:\s*([A-Za-z ]+)", c)
    online = c[:c.find("Technical")] if "Technical" in c else ""
    mins = re.search(r"(\d+)\s*minutes", online)
    sections = [name for name, rx in (("reasoning", r"reasoning"), ("quantitative", r"quantitative|maths"),
                                      ("verbal", r"verbal"), ("sql", r"sql")) if re.search(rx, online, re.I)]
    return {"url": p["url"], "date": p["date"], "title": p["title"], "result": res.group(1).strip() if res else "?",
            "tech": tech, "hr": hr,
            "online": {"sections": sections, "minutes": int(mins.group(1)) if mins else None,
                       "strict_timer": "strict timer" in online.lower()}}


def aggregate(reports, kind, rules):
    by = {}
    for r in reports:
        seen = set()
        for q in r[kind]:
            for topic, subj in classify(q, rules):
                if topic in seen:
                    continue
                seen.add(topic)
                d = by.setdefault(topic, {"topic": topic, "subject": subj, "count": 0, "sources": [],
                                          "example": q, "latest": ""})
                d["count"] += 1
                d["sources"].append({"url": r["url"], "date": r["date"], "title": r["title"]})
                if r["date"] > d["latest"]:
                    d["latest"], d["example"] = r["date"], q
    return sorted(by.values(), key=lambda d: (-d["count"], -int(d["latest"].replace("-", ""))))


def parse_job(p):
    c = p["content"]
    skills = []
    m = re.search(r"Skills:\s*(.*?)\.\s*Selection", c)
    for s in split_top(m.group(1)) if m else []:
        skills.append({"name": s, "key": skill_key(s)})
    cut = re.search(r"(\d+)%\s*or\s*([\d.]+)\s*CGPA", c)
    yrs = re.search(r"Graduates of (\d{4}) and (\d{4})", c)
    loc = re.search(r"Location:\s*(\w+)", c)
    proc = re.search(r"Selection process:\s*(.*?)\.", c)
    cond = re.search(r"(Willingness[^.]*)\.", c)
    return {"title": p["title"], "url": p["url"], "date": p["date"], "company": p["company"],
            "location": loc.group(1) if loc else None, "skills": skills,
            "min_cgpa": float(cut.group(2)) if cut else None, "min_pct": int(cut.group(1)) if cut else None,
            "grad_years": [int(yrs.group(1)), int(yrs.group(2))] if yrs else [],
            "process": [x.strip() for x in proc.group(1).split(",")] if proc else [],
            "conditions": cond.group(1) if cond else "", "level": "entry (0-1 years)"}


def parse_resume(p):
    c = p["content"]
    g = lambda rx: (re.search(rx, c, re.S).group(1) if re.search(rx, c, re.S) else "")
    order = [x.strip() for x in g(r"Order:\s*(.*?)\.\s").split(",") if x.strip()]
    skills = [re.sub(r"\s*\(.*", "", s).strip() for s in split_top(g(r"Skills:\s*(.*?)\.\s+Projects"))]
    projects = [x.strip() for x in g(r"Projects:\s*(.*?)\.\s+Cert").split(";") if x.strip()]
    certs = [x.strip() for x in split_top(g(r"Certifications:\s*(.*?)\.(?:\s|$)"))]
    return {"url": p["url"], "date": p["date"], "title": p["title"], "order": order, "skills": skills,
            "projects": projects, "certs": certs,
            "bcom": "b.com" in c.lower(), "quantified": "number" in c or "quantified" in c.lower()}


async def run(ctx):
    goal = ctx.get("goal")
    company = goal["company"]
    t = ctx.tools
    catalog = t.catalog()                                              # free metadata, no content
    accepted, rejected = webfilter.screen_catalog(catalog, company, ctx.today)
    type_of = {p["url"]: p["type"] for p in catalog}
    for r in rejected:
        r["type"] = type_of[r["url"]]
    sanitized = []

    def read(meta, browser=False):
        page = t.browse(meta["url"]) if browser else t.fetch(meta["url"])
        clean, verdict = webfilter.screen_content(page["content"])
        if verdict["reject"]:
            rejected.append({"url": meta["url"], "title": meta["title"], "type": meta["type"],
                             "reason": verdict["reject"], "stage": "content"})
            return None
        if verdict["stripped"]:
            sanitized.append({"url": meta["url"], "stripped": verdict["stripped"]})
        return {**page, "content": clean}

    newest = lambda lst: sorted(lst, key=lambda p: p["date"], reverse=True)
    of_type = lambda ty: newest([p for p in accepted if p["type"] == ty])

    # job post (official domain only; the lookalike scam page was already dropped for free)
    job = None
    for meta in of_type("job_post")[:1]:
        page = read(meta)
        job = parse_job(page) if page else None
    if job is None:
        ctx.warn(f"no official job post found for {company}")

    # interview reports: fetch the fetchable ones; browse (Rs 5) only if we lack evidence
    reports_meta = of_type("interview_report")
    fetchable = [m for m in reports_meta if not m["needs_browser"]]
    browser_only = [m for m in reports_meta if m["needs_browser"]]
    reports = [parse_report(pg) for m in fetchable if (pg := read(m))]
    skipped_browse = []
    for m in browser_only:
        if len(reports) < MIN_REPORTS:
            pg = read(m, browser=True)
            if pg:
                reports.append(parse_report(pg))
                ctx.warn(f"browsed {m['url']} (Rs 5) because only {len(reports) - 1} fetchable reports")
        else:
            skipped_browse.append({"url": m["url"], "date": m["date"], "title": m["title"],
                                   "saved_rs": t.w.costs["browse"],
                                   "risk": "may hold newer questions we do not have"})
    reports.sort(key=lambda r: r["date"], reverse=True)

    resumes = [parse_resume(pg) for m in of_type("placed_resume")[:MAX_RESUMES] if (pg := read(m))]
    news = [{"title": pg["title"], "url": pg["url"], "date": pg["date"], "text": pg["content"]}
            for m in of_type("news")[:MAX_NEWS] if (pg := read(m))]
    tips = []
    for m in of_type("blog"):
        pg = read(m)
        if pg:
            for n in re.findall(r"\d\)\s*(.+?)(?=\s+\d\)|$)", pg["content"]):
                tips.append({"text": n.strip().rstrip("."), "url": m["url"], "date": m["date"], "trust": "blog, unverified"})

    interviews = {"company": company, "n": len(reports), "reports": reports,
                  "tech": aggregate(reports, "tech", TECH_RULES), "hr": aggregate(reports, "hr", HR_RULES)}
    mins = Counter(r["online"]["minutes"] for r in reports if r["online"]["minutes"])
    sec_count = Counter(s for r in reports for s in r["online"]["sections"])
    test_format = {"minutes": mins.most_common(1)[0][0] if mins else None,
                   "sections": [s for s, n in sec_count.items() if n >= 2],
                   "strict_timer": any(r["online"]["strict_timer"] for r in reports),
                   "sources": [{"url": r["url"], "date": r["date"]} for r in reports if r["online"]["minutes"]]}
    orders = Counter(tuple(r["order"]) for r in resumes)
    certs = Counter(c for r in resumes for c in r["certs"])
    res_skills = Counter(s for r in resumes for s in r["skills"])
    resumes_agg = {"n": len(resumes), "section_order": list(orders.most_common(1)[0][0]) if orders else [],
                   "skills": dict(res_skills), "certs": dict(certs), "peers": resumes,
                   "bullet_style": "action + tool + number"}
    conf = "high" if (len(reports) >= 4 and job) else "medium" if len(reports) >= 2 else "low"

    for k, v in {"meta": {"company": company, "role": goal["role"], "city": goal["city"], "built": str(ctx.today)},
                 "job": job, "interviews": interviews, "test_format": test_format, "resumes": resumes_agg,
                 "news": news, "tips": tips, "rejected": rejected, "sanitized": sanitized,
                 "skipped_browse": skipped_browse, "confidence": conf}.items():
        ctx.put(f"research.{k}", v)

    if reports:
        top = interviews["tech"][0]
        ctx.remember("fact", f"{company.lower()}_interviews",
                     f"Research: {len(reports)} usable {company} reports (latest {reports[0]['date']}); "
                     f"most asked: {top['topic']} ({top['count']}/{len(reports)})", source=reports[0]["url"])
    for r in rejected:
        if r["stage"] == "content":
            ctx.warn(f"rejected {r['url']}: {r['reason']}")
