"""Long-term memory: append-only notes + reusable artifacts, per user, in a JSON file.

Note: {agent, type: fact|score|own_words|coaching, topic, text, source, value, polarity, ts}
Artifacts: expensive results worth reusing next session (research, resume, test results, pending actions).

Conflicts are kept both ways. A claim ("I'm good at SQL") never gets deleted; a measured score on the same
topic wins for *planning*, and the claim only informs the tone of coaching.
"""
import copy
import json
import os

WEAK = 0.6

# who should see which kind of note (summary_for)
RELEVANT = {
    "grace": {"score", "own_words", "fact", "coaching"},
    "vera": {"score", "own_words", "coaching"},
    "sage": {"own_words", "score", "coaching"},
    "kai": {"own_words", "coaching", "fact"},
    "mira": {"own_words", "fact", "score"},
    "lyra": {"score", "own_words"},
    "nova": {"own_words", "fact", "score"},
    "scout": {"fact", "score"},
}


class Memory:
    def __init__(self, path=None):
        self.path = path
        self.db = {"users": {}}
        if path and os.path.exists(path):
            with open(path) as f:
                self.db = json.load(f)

    # ---- persistence ----------------------------------------------------
    def save(self):
        if self.path:
            with open(self.path, "w") as f:
                json.dump(self.db, f, indent=2, default=str)

    def reset(self):
        self.db = {"users": {}}
        self.save()

    def _u(self, uid):
        return self.db["users"].setdefault(uid, {"sessions": [], "notes": [], "artifacts": {}})

    def forget(self, uid):
        self.db["users"].pop(uid, None)

    def share_artifact(self, src_uid, dst_uid, name):
        """Copy a company-level artifact (no personal data) to another user: the cohort cache."""
        a = self._u(src_uid)["artifacts"].get(name)
        if a:
            self._u(dst_uid)["artifacts"][name] = copy.deepcopy(a)

    def exists(self, uid) -> bool:
        return uid in self.db["users"] and bool(self.db["users"][uid]["sessions"])

    # ---- writing --------------------------------------------------------
    def write(self, uid, note: dict, today):
        u = self._u(uid)
        note = dict(note)
        note["ts"] = str(today)
        key = (note["agent"], note["type"], note["topic"], note["text"])
        if any((n["agent"], n["type"], n["topic"], n["text"]) == key for n in u["notes"]):
            return False  # identical note already stored
        u["notes"].append(note)
        return True

    def ingest_profile(self, user: dict, today):
        """Grace's intake: the user's own words are memory too (stored once, tagged with topic/polarity)."""
        tag = {
            "good at sql": ("sql", "strength"),
            "nervous when a test has a timer": ("timed_tests", "anxiety"),
            "finding patterns": ("sales_data_analysis", "interest"),
        }
        for words in user.get("own_words", []):
            topic, pol = "general", "neutral"
            for k, (t, p) in tag.items():
                if k in words.lower():
                    topic, pol = t, p
            self.write(user["id"], {"agent": "user", "type": "own_words", "topic": topic, "text": words,
                                    "source": "intake", "value": None, "polarity": pol}, today)

    def save_artifacts(self, uid, today, **arts):
        u = self._u(uid)
        for name, data in arts.items():
            if data:
                u["artifacts"][name] = {"built": str(today), "data": copy.deepcopy(data)}

    def log_session(self, uid, day, today):
        self._u(uid)["sessions"].append({"day": day, "date": str(today)})

    # ---- reading --------------------------------------------------------
    def artifact(self, uid, name):
        a = self._u(uid)["artifacts"].get(name)
        return copy.deepcopy(a) if a else None

    def scores(self, uid) -> dict:
        out = {}
        for n in self._u(uid)["notes"]:          # later score wins
            if n["type"] == "score" and n.get("value") is not None:
                out[n["topic"]] = n["value"]
        return out

    def conflicts(self, uid):
        u = self._u(uid)
        scores = self.scores(uid)
        out = []
        for n in u["notes"]:
            if n["type"] == "own_words" and n.get("polarity") == "strength":
                measured = {t: v for t, v in scores.items() if t == n["topic"] or t.startswith(n["topic"] + ":")}
                weak = {t: v for t, v in measured.items() if v < WEAK}
                if weak:
                    t = min(weak, key=weak.get)
                    out.append({"claim": n["text"], "topic": n["topic"], "measured_topic": t,
                                "measured": weak[t],
                                "resolution": "plan on the measured score; keep the claim only to shape coaching tone"})
        return out

    def recall(self, uid) -> dict:
        u = self._u(uid)
        scores = self.scores(uid)
        return {
            "sessions": len(u["sessions"]),
            "n_notes": len(u["notes"]),
            "scores": scores,
            "weak_topics": sorted([t for t, v in scores.items() if v < WEAK], key=lambda t: scores[t]),
            "own_words": [{"text": n["text"], "topic": n["topic"], "polarity": n.get("polarity")}
                          for n in u["notes"] if n["type"] == "own_words"],
            "conflicts": self.conflicts(uid),
            "artifacts": {k: {"built": v["built"]} for k, v in u["artifacts"].items()},
        }

    def summary_for(self, uid, agent: str, limit=6) -> list:
        """'What do we know about this user?', filtered to what this agent can use."""
        u = self._u(uid)
        want = RELEVANT.get(agent, {"score", "own_words"})
        lines = []
        for c in self.conflicts(uid):
            lines.append(f"CONFLICT: says \"{c['claim']}\" but measured {c['measured_topic']} = "
                         f"{round(c['measured'] * 100)}% (trust measurement)")
        for n in reversed(u["notes"]):
            if n["type"] in want and n["agent"] != "grace":
                tag = "says" if n["type"] == "own_words" else n["agent"]
                lines.append(f"{tag}: {n['text']}")
        seen, out = set(), []
        for l in lines:
            if l not in seen:
                seen.add(l)
                out.append(l)
        return out[:limit]
