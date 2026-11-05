"""Shared helpers for agents: skill normalisation, profile evidence, source formatting."""
import re


def skill_key(name: str) -> str:
    n = name.lower()
    for k, v in (("sql", "sql"), ("excel", "excel"), ("power bi", "power bi"), ("tableau", "power bi"),
                 ("python", "python"), ("communication", "communication")):
        if k in n:
            return v
    return n.strip()


def skill_label(key: str) -> str:
    return {"sql": "SQL", "excel": "Excel", "power bi": "Power BI", "python": "Python",
            "communication": "Communication"}.get(key, key.title())


def profile_skills(profile: dict) -> dict:
    """Claimed skills -> {key: {level, strength, evidence:[record ids]}}. Evidence comes from records only."""
    out = {}
    for s in profile.get("skills_claimed", []):
        k = skill_key(s)
        ev, level = [], "claimed only"
        for r in profile.get("records", []):
            text = f"{r['title']} {r['detail']}".lower()
            hit = (k == "sql" and "sql" in text) or (k == "excel" and "excel" in text) or \
                  (k == "communication" and ("presented" in text)) or \
                  (k == "power bi" and ("power bi" in text or "tableau" in text)) or \
                  (k == "python" and "python" in text)
            if hit:
                ev.append(r["id"])
                if "basic" in text:
                    level = "basic"
                elif level != "basic":
                    level = "working"
        strength = {"claimed only": 0.3, "basic": 0.5, "working": 0.8}[level]
        out[k] = {"level": level, "strength": strength, "evidence": ev}
    return out


def src(item) -> str:
    """Format a source for display: 'host/path (date)'."""
    url = item["url"] if isinstance(item, dict) else item
    d = item.get("date", "") if isinstance(item, dict) else ""
    short = re.sub(r"^https?://", "", url)
    return f"{short} ({d})" if d else short


def top_src(sources: list) -> str:
    if not sources:
        return "no source"
    latest = max(sources, key=lambda s: s["date"])
    return src(latest)


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


# ---- shared helpers added for the agents -----------------------------------------------------------
def anxious_about_timers(recall) -> bool:
    return any(w.get("topic") == "timed_tests" for w in (recall or {}).get("own_words", []))


def own_words_for(recall, topic):
    for w in (recall or {}).get("own_words", []):
        if w.get("topic") == topic:
            return w["text"]
    return None


def claim_gap(recall, results, profile) -> list:
    """Claim vs evidence. Measured test scores win; otherwise fall back to the strength of the records."""
    out = []
    for w in (recall or {}).get("own_words", []):
        if w.get("polarity") != "strength":
            continue
        topic = w["topic"]
        scored = [r for r in (results or []) if r["topic"] == topic or r["topic"].startswith(topic + ":")]
        if scored:
            worst = min(scored, key=lambda r: r["score"])
            if worst["score"] < 0.6:
                out.append({"claim": w["text"], "topic": topic, "measured": worst["score"],
                            "measured_topic": worst["topic"], "basis": "test"})
        else:
            ps = profile_skills(profile).get(skill_key(topic))
            if ps and ps["strength"] < 0.6:
                out.append({"claim": w["text"], "topic": topic, "measured": ps["strength"],
                            "measured_topic": topic, "basis": f"records ({ps['level']})"})
    return out


def find_topic(interviews, kind, topic):
    for d in (interviews or {}).get(kind, []):
        if d["topic"] == topic:
            return d
    return None


def cite(interviews, kind, topic):
    """'asked in 3 of 4 Infosys reports; latest host/path (date)', or None if no source supports it."""
    d = find_topic(interviews, kind, topic)
    if not d:
        return None
    latest = max(d["sources"], key=lambda s: s["date"])
    return f"asked in {d['count']} of {interviews['n']} {interviews.get('company', '')} reports; latest {src(latest)}"


def skill_gaps(profile, job) -> list:
    """Job-required skills where our evidence is weak. Evidence comes from records only."""
    have = profile_skills(profile)
    out = []
    for js in (job or {}).get("skills", []):
        k = js["key"]
        st = have.get(k, {"strength": 0.0, "level": "no evidence", "evidence": []})
        if st["strength"] < 0.6:
            out.append({"skill": k, "label": skill_label(k), "level": st["level"], "strength": st["strength"],
                        "required_by": js["name"]})
    return out


def cgpa_of(profile) -> float:
    try:
        return float(re.search(r"[\d.]+", profile["education"][0]["score"]).group())
    except Exception:
        return 0.0
