"""Grace: parses the sentence into INTENTS, maps intents to agents, and builds the PLAN AS DATA.

sentence -> goal {role, company, city, intents} -> agents chosen by intent (+ what they need) -> memory trims
what is already known -> validated Step list. The executor never decides anything.

Intent -> agents is a table (INTENTS). Dependencies are pulled in automatically:
  * every HARD dependency of a chosen agent (Scout needs research),
  * research whenever any chosen agent reads research.* (relevance to the company),
  * approval whenever Scout or Nova is chosen (or something is already waiting for the user's OK),
  * grace_summary always.
"""
import re
from datetime import date

from agents import AGENTS
from core.plan import Plan, Step

FRESH_DAYS = 7

# agent -> (dependencies, which of them are soft = tolerate failure and run degraded)
DEPS = {
    "research": ([], []),
    "scout": (["research"], []),
    "sage": (["research"], []),
    "mira": (["research"], ["research"]),
    "kai": (["research", "sage"], ["research", "sage"]),
    "vera": (["research", "sage"], ["sage"]),
    "lyra": (["research", "sage", "mira"], ["sage", "mira"]),
    "nova": (["research", "sage"], ["research", "sage"]),
    "approval": (["scout", "nova"], ["scout", "nova"]),
    "grace_summary": (["research", "scout", "sage", "mira", "kai", "vera", "lyra", "nova", "approval"],
                      ["research", "scout", "sage", "mira", "kai", "vera", "lyra", "nova", "approval"]),
}
ORDER = list(DEPS)

# intent -> (what the user is asking for, agents that serve it directly)
INTENTS = {
    "get_hired": ("full package: find the job, then get ready for it", ["scout", "sage", "mira", "kai", "vera", "lyra", "nova"]),
    "find_job": ("find and rank matching jobs", ["scout"]),
    "prepare_interview": ("practise the technical and HR rounds", ["sage", "vera", "kai"]),
    "fix_resume": ("write / tailor the resume", ["mira"]),
    "learn_skills": ("close skill gaps", ["sage", "mira", "lyra"]),
    "build_brand": ("LinkedIn presence", ["nova"]),
    "test_skills": ("objective skills test", ["sage"]),
}
# checked in order; the first nine words of the sentence that match are kept as evidence
INTENT_PATTERNS = [
    ("fix_resume", r"\b(resume|cv)\b"),
    ("prepare_interview", r"\b(interview|mock|practi[sc]e|prepare|preparation)\b"),
    ("learn_skills", r"\b(learn|course|courses|upskill|skill gaps?|study)\b"),
    ("build_brand", r"\b(linkedin|personal brand|post)\b"),
    ("test_skills", r"\b(test me|assess me|quiz|skills? test|test my)\b"),
    ("find_job", r"\b(find|search|apply)\b.*\b(jobs?|openings?|roles?)\b|\bopenings\b"),
    ("get_hired", r"\b(want|looking for|need|get me|land|get)\b.*\bjob\b"),
]
ROLE_HINTS = ["data analyst"]


def detect_intents(sentence: str) -> list:
    found = []
    for intent, rx in INTENT_PATTERNS:
        m = re.search(rx, sentence, re.I)
        if m:
            found.append({"intent": intent, "matched": m.group(0)})
    if any(f["intent"] == "get_hired" for f in found):
        found = [f for f in found if f["intent"] == "get_hired"]   # the full package already covers the rest
    if not found:
        found = [{"intent": "get_hired", "matched": "(no specific ask recognised: default full package)"}]
    return found


def parse_goal(sentence: str, profile: dict, companies=()) -> dict:
    s = sentence
    company = next((c for c in companies if re.search(rf"\b{re.escape(c)}\b", s, re.I)), None)
    if not company:
        m = re.search(r"\bat\s+([A-Za-z]+)", s)
        company = m.group(1) if m else None
    role = re.search(r"(?:a|an)\s+(.+?)\s+job", s, re.I)
    role = role.group(1).lower() if role else next((r for r in ROLE_HINTS if r in s.lower()), None)
    city = re.search(r"\bin\s+([A-Za-z]+)", s)
    return {"sentence": s, "role": role, "company": company, "city": city.group(1) if city else None,
            "level": "entry" if not profile.get("experience") else "experienced",
            "intents": detect_intents(s)}


def select_agents(goal, pending_actions: bool) -> dict:
    """intent -> agents, then add what they need. Returns {agent: reason}."""
    why = {}
    for it in goal["intents"]:
        for a in INTENTS[it["intent"]][1]:
            why.setdefault(a, f"intent '{it['intent']}'")
    changed = True
    while changed:                                              # hard dependencies, transitively
        changed = False
        for a in list(why):
            deps, soft = DEPS[a]
            for d in deps:
                if d not in soft and d not in why:
                    why[d] = f"required by {a}"
                    changed = True
    users = [a for a in why if any(k.startswith("research") for k in AGENTS[a].SPEC["reads"] + AGENTS[a].SPEC.get("optional_reads", []))]
    if users and "research" not in why:
        why["research"] = f"company facts for {', '.join(users)}"
    if ("scout" in why or "nova" in why or pending_actions) and "approval" not in why:
        why["approval"] = "something may need the user's OK"
    why["grace_summary"] = "always: one answer for the user"
    return why


def _age(built: str, today: date) -> int:
    return (today - date.fromisoformat(built)).days


def plan(goal, recall, cfg, memory, uid) -> Plan:
    arts = recall["artifacts"]
    today = cfg.today
    actions = memory.artifact(uid, "actions")
    pending = bool(actions and any(a.get("status") == "pending_approval" for a in actions["data"].values()))
    chosen = select_agents(goal, pending)
    notes = ["intents: " + "; ".join(f"{i['intent']} (matched '{i['matched']}')" for i in goal["intents"])]

    skip = {}                                                   # memory trims chosen agents whose result we already have
    r = memory.artifact(uid, "research")
    if r and r["data"].get("meta", {}).get("company") == goal["company"] and _age(r["built"], today) <= FRESH_DAYS:
        skip["research"] = (f"company research is {_age(r['built'], today)}d old (<= {FRESH_DAYS}d) and matches "
                            f"{goal['company']}: reused, Rs 0 on web tools" if recall["sessions"] else
                            f"{goal['company']} research reused from the shared cohort cache (company-level, no personal data)")
    if "test" in arts and recall["scores"]:
        skip["sage"] = "scores already known (" + ", ".join(f"{t} {round(v * 100)}%" for t, v in recall["scores"].items()) + ")"
    if "resume" in arts:
        skip["mira"] = "resume already built; nothing in the profile changed"
    if "scout" in arts:
        skip["scout"] = "job ranking unchanged; application carried over for approval"
    if actions and actions["data"].get("nova", {}).get("status") == "pending_approval":
        skip["nova"] = "a post draft is still waiting for your OK; not stacking a second one"
    if recall["sessions"]:
        notes.append(f"returning user: {recall['sessions']} earlier session(s), {recall['n_notes']} notes in memory")
        if recall["weak_topics"]:
            notes.append("weak topics from memory drive Vera/Kai/Lyra: " + ", ".join(recall["weak_topics"]))

    asked = ", ".join(i["intent"] for i in goal["intents"])
    skipped, inc = [], []
    for a in ORDER:
        if a not in chosen:
            skipped.append({"agent": a, "reason": f"not needed for intent: {asked}"})
        elif a in skip:
            skipped.append({"agent": a, "reason": skip[a]})
        else:
            inc.append(a)
    steps = []
    for a in inc:
        deps, soft = DEPS[a]
        spec = AGENTS[a].SPEC
        params = {}
        if a in ("vera", "kai"):
            params["focus"] = recall["weak_topics"] or "from research"
        if a == "lyra":
            params["days_left"] = cfg.days_left
        steps.append(Step(id=a, agent=a, depends_on=[d for d in deps if d in inc], soft=[d for d in soft if d in inc],
                          reads=list(spec["reads"]), optional_reads=list(spec.get("optional_reads", [])),
                          writes=list(spec["writes"]), params=params, why=chosen[a]))
    return Plan(steps=steps, skipped=skipped, notes=notes)
