import asyncio
import json
import os
import unittest
from datetime import date

import main
from agents import grace
from agents.common import skill_gaps
from core.cost import CostMeter
from core.executor import Config
from core.memory import Memory
from core.plan import Plan, PlanError, Step, validate
from core.state import Ctx, State, UndeclaredAccess
from core.trace import Trace
from tools import webfilter
from tools.tools import NeedsBrowser, Tools, World, run_sql_sandbox

DATA = json.load(open(os.path.join(os.path.dirname(main.__file__), "demo_data.json")))
SENT = "I want a data analyst job at Infosys in Bangalore."


def run(cfg=None, memory=None, sentence=SENT):
    cfg = cfg or Config(today=date(2026, 11, 5))
    meter, memory = CostMeter(), memory or Memory(None)
    r = asyncio.run(main.run_user(DATA["user"], sentence, World(DATA), meter, memory, cfg, Trace(False)))
    return r, meter, memory


class PlanTests(unittest.TestCase):
    def test_cycle_rejected(self):
        p = Plan([Step("a", "x", depends_on=["b"]), Step("b", "x", depends_on=["a"])])
        with self.assertRaises(PlanError):
            validate(p, [])

    def test_overlapping_writes_rejected(self):
        p = Plan([Step("a", "x", writes=["k"]), Step("b", "x", writes=["k.sub"])])
        with self.assertRaises(PlanError):
            validate(p, [])

    def test_read_without_producer_rejected(self):
        with self.assertRaises(PlanError):
            validate(Plan([Step("a", "x", reads=["nope"])]), [])

    def test_undeclared_access_raises(self):
        ctx = Ctx(Step("a", "x"), {"reads": ["goal"], "writes": ["out"]}, State({"goal": 1, "secret": 2}), None, None, "u", None, [])
        with self.assertRaises(UndeclaredAccess):
            ctx.get("secret")
        with self.assertRaises(UndeclaredAccess):
            ctx.put("other", 1)


class ToolAndTrustTests(unittest.TestCase):
    def test_fetch_fails_on_browser_page(self):
        t = Tools(World(DATA), CostMeter(), "s")
        with self.assertRaises(NeedsBrowser):
            t.fetch("https://forum.campushire.example/t/infosys-data-analyst-2025")

    def test_scam_and_lookalike_rejected_free(self):
        cat = Tools(World(DATA), CostMeter(), "s").catalog()
        ok, rej = webfilter.screen_catalog(cat, "Infosys", date(2026, 11, 5))
        urls = {r["url"] for r in rej}
        self.assertIn("https://infosys-careers-hiring.example/guaranteed-data-analyst", urls)
        self.assertIn("https://interviewstories.example/infosys/data-analyst-2021", urls)
        self.assertFalse(any(p["company"] in ("TCS", "Zomato") for p in ok))

    def test_injection_stripped(self):
        page = next(p for p in DATA["pages"] if p["type"] == "blog")
        clean, v = webfilter.screen_content(page["content"])
        self.assertNotIn("SuperSQL", clean)
        self.assertTrue(v["stripped"])

    def test_sandbox_blocks_writes(self):
        self.assertFalse(run_sql_sandbox("DROP TABLE employee")["ok"])
        self.assertFalse(run_sql_sandbox("SELECT 1; DROP TABLE employee")["ok"])
        self.assertTrue(run_sql_sandbox("SELECT MAX(salary) FROM employee")["ok"])


class FlowTests(unittest.TestCase):
    def test_day1_cost_and_no_browse(self):
        r, meter, _ = run()
        self.assertEqual(meter.calls("browse"), 0)
        self.assertEqual(meter.total(), 6.10)
        self.assertTrue(all(s["state"] == "ok" for s in r["status"].values()))

    def test_sage_catches_wrong_join(self):
        r, _, _ = run()
        scores = {x["topic"]: x["score"] for x in r["state"].data["test.results"]}
        self.assertEqual(scores, {"sql:second_highest": 1.0, "sql:joins": 0.4})

    def test_resume_never_lists_unevidenced_skills(self):
        r, _, _ = run()
        self.assertEqual({s["skill"] for s in r["state"].data["resume.sections"]["skills"]}, {"Excel", "SQL", "Communication"})
        self.assertEqual(r["state"].data["resume.sections"]["certifications"], [])

    def test_nothing_applied_without_approval(self):
        r, _, _ = run()
        self.assertEqual(r["state"].data["approvals.scout"]["status"], "pending_approval")
        self.assertEqual(r["state"].data["approvals.nova"]["status"], "pending_approval")
        r2, _, _ = run(Config(today=date(2026, 11, 5), approve=True))
        self.assertEqual(r2["state"].data["approvals.scout"]["status"], "applied")

    def test_failure_survives_and_degrades(self):
        r, _, _ = run(Config(today=date(2026, 11, 5), fail={"sage"}))
        st = r["status"]
        self.assertEqual(st["sage"]["state"], "failed")
        self.assertEqual(st["vera"]["state"], "degraded")
        self.assertTrue(r["card"]["not_completed"])

    def test_hard_dependency_failure_skips(self):
        r, _, _ = run(Config(today=date(2026, 11, 5), fail={"research"}))
        self.assertEqual(r["status"]["scout"]["state"], "skipped")
        self.assertIn("card", r["state"].data)

    def test_summary_failure_uses_fallback_card(self):
        r, _, _ = run(Config(today=date(2026, 11, 5), fail={"grace_summary"}))
        self.assertTrue(r["card"]["headline"].startswith("Partial plan"))

    def test_flaky_agent_retries(self):
        r, _, _ = run(Config(today=date(2026, 11, 5), flaky={"mira"}))
        self.assertEqual(r["status"]["mira"]["state"], "ok")

    def test_day2_reuses_memory_and_costs_less(self):
        _, m1, mem = run()
        cfg2 = Config(day=2, today=date(2026, 11, 6), days_left=13)
        r2, m2, _ = run(cfg2, mem)
        skipped = {s["agent"] for s in r2["plan"].skipped}
        self.assertTrue({"research", "sage", "mira", "scout"} <= skipped)
        self.assertEqual(m2.calls("fetch"), 0)
        self.assertLess(m2.total(), m1.total())
        self.assertEqual(mem.recall("u_priya")["conflicts"][0]["measured_topic"], "sql:joins")

    def test_day2_replans_sage_if_day1_sage_failed(self):
        _, _, mem = run(Config(today=date(2026, 11, 5), fail={"sage"}))
        r2, _, _ = run(Config(day=2, today=date(2026, 11, 6), days_left=13), mem)
        self.assertIn("sage", [s.agent for s in r2["plan"].steps])

    def test_intent_changes_the_plan(self):
        cases = {"Fix my resume for a data analyst job at Infosys": ({"research", "mira", "grace_summary"}, {"scout", "sage", "vera"}),
                 "Find me data analyst openings at Infosys in Bangalore": ({"research", "scout", "approval"}, {"mira", "vera", "nova"}),
                 "Help me prepare for my Infosys data analyst interview": ({"sage", "vera", "kai"}, {"scout", "mira", "nova"})}
        for sentence, (must, never) in cases.items():
            r, meter, _ = run(sentence=sentence)
            ran = {s.agent for s in r["plan"].steps}
            self.assertTrue(must <= ran, (sentence, ran))
            self.assertFalse(never & ran, (sentence, ran))
            self.assertLess(meter.total(), 6.10)

    def test_default_sentence_is_the_full_package(self):
        r, _, _ = run()
        self.assertEqual([i["intent"] for i in r["state"].data["goal"]["intents"]], ["get_hired"])
        self.assertEqual(len(r["plan"].steps), 10)

    def test_partial_card_does_not_claim_missing_job(self):
        r, _, _ = run(sentence="Fix my resume for a data analyst job at Infosys")
        self.assertIsNone(r["card"]["jobs"])
        self.assertTrue(r["card"]["tailored"])

    def test_tcs_has_no_job_and_says_so(self):
        r, _, _ = run(sentence=SENT.replace("Infosys", "TCS"))
        self.assertEqual(r["card"]["jobs"], [])
        self.assertTrue(any("confidence" in n for n in r["card"]["notes"]))

    def test_every_vera_question_has_a_dated_source(self):
        r, _, _ = run()
        for q in r["state"].data["vera.questions"]:
            self.assertRegex(q["why_asked"], r"\(\d{4}-\d{2}-\d{2}\)")


if __name__ == "__main__":
    unittest.main()
