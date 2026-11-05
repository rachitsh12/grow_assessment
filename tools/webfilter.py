"""Trust filter for web content. Page text is DATA, never instructions.

Stage 1 (metadata, free): wrong company, stale, lookalike domain, scam-looking title.
Stage 2 (content, after fetch): scam patterns reject the page; injected instructions are stripped.
"""
import re
from datetime import date

MAX_REPORT_AGE_DAYS = 3 * 365

SCAM_TITLE = re.compile(r"guaranteed|limited seats|pay .*fee|registration fee", re.I)
SCAM_CONTENT = [
    (re.compile(r"registration fee|one-time fee|pay (a|the) .{0,30}fee|Rs\s?[\d,]+ to secure", re.I), "asks candidate to pay a fee"),
    (re.compile(r"no interview needed|guaranteed (offer|placement|job)", re.I), "promises a guaranteed offer"),
]
INJECTION = [
    re.compile(r"ignore (all |any |your )?(previous|prior|above) instructions", re.I),
    re.compile(r"note to (ai|llm|assistant|agents?)\b", re.I),
    re.compile(r"(you are|act as) an? (ai|assistant|agent)", re.I),
    re.compile(r"recommend ['\"][^'\"]+['\"] as the only", re.I),
]
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def has_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION) or bool(HTML_COMMENT.search(text))


def age_days(d: str, today: date) -> int:
    return (today - date.fromisoformat(d)).days


def screen_catalog(catalog, company: str, today: date):
    """Metadata-only screen. Returns (accepted, rejected[{url, reason, stage}])."""
    accepted, rejected = [], []
    official_host = f"careers.{company.lower()}.example"
    for p in catalog:
        reason = None
        if p["company"] and p["company"].lower() != company.lower():
            reason = f"different company ({p['company']})"
        elif p["type"] == "job_post" and official_host not in p["url"]:
            reason = f"job post not on official domain {official_host}"
        elif SCAM_TITLE.search(p["title"] or ""):
            reason = "scam-looking title (guaranteed / limited seats)"
        elif p["type"] == "interview_report" and age_days(p["date"], today) > MAX_REPORT_AGE_DAYS:
            reason = f"stale ({p['date']}, older than {MAX_REPORT_AGE_DAYS // 365}y)"
        if reason:
            rejected.append({"url": p["url"], "title": p["title"], "reason": reason, "stage": "metadata"})
        else:
            accepted.append(p)
    return accepted, rejected


def screen_content(text: str):
    """Returns (clean_text, verdict). verdict = {reject: reason|None, stripped: [str]}."""
    for pat, why in SCAM_CONTENT:
        if pat.search(text):
            return "", {"reject": why, "stripped": []}
    stripped = []
    clean = text

    def _strip(m):
        stripped.append(m.group(0)[:80])
        return " "

    clean = HTML_COMMENT.sub(_strip, clean)
    # drop any remaining sentence that looks like an instruction aimed at an AI
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    kept = []
    for s in sentences:
        if any(p.search(s) for p in INJECTION):
            stripped.append(s[:80])
        else:
            kept.append(s)
    return re.sub(r"\s+", " ", " ".join(kept)).strip(), {"reject": None, "stripped": stripped}
