"""Проверки без платных вызовов: python -m unittest discover tests -v"""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from persuasion import deepseek, plan, prompts, store, trial

PROJECT = store.ROOT


class TrialTests(unittest.TestCase):
    def setUp(self):
        """Копия настроек и текстов во временном корне; субагентам назначены тестовые модели."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copy(PROJECT / "topics.json", self.root)
        shutil.copytree(PROJECT / "prompts", self.root / "prompts")
        cfg = store.read_json(PROJECT / "config.json")
        for name, item in cfg["profiles"].items():
            if item["transport"] == "subagent":
                item["model"] = f"test-{name}"
        self.write_config(cfg)
        self.patch(store, "ROOT", self.root)
        self.api_calls = []
        self.patch(deepseek, "call", self.fake_api)

    def patch(self, target, name, value):
        context = patch.object(target, name, value)
        context.start()
        self.addCleanup(context.stop)

    def write_config(self, cfg):
        (self.root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def fake_api(self, model, scope, messages):
        self.api_calls.append((model, copy.deepcopy(messages)))
        question = messages[-1]["content"]
        if '"persuasiveness"' in question:
            return '{"score":1,"persuasiveness":4,"manipulativeness":2}'
        if '"score"' in question:
            return '{"score":3}'
        return "API debate text"

    def envelope(self, packet, content=None):
        """Ответ субагента: позиция 3 до диалога и 1 после, то есть сдвиг 2."""
        if content is None:
            if packet["fields"]:
                values = {key: 3 for key in packet["fields"]}
                if "persuasiveness" in values:
                    values["score"] = 1
                content = json.dumps(values)
            else:
                content = "Subagent debate text"
        return {"request_id": packet["request_id"], "content": content,
                "execution": {**{k: packet["profile"][k] for k in ("engine", "model", "settings")},
                              "session_id": "session-" + packet["request_id"]}}

    def run_trial(self, pair, mode="persuade"):
        started = trial.start(pair=pair, mode=mode, topic_id="topic_01")
        packets = []
        for _ in range(80):
            step = trial.advance(started["id"])
            if step["done"]:
                return store.read_json(store.run_file("results", started["id"])), packets
            packets.append(step["request"])
            trial.submit(started["id"], self.envelope(step["request"]))
        self.fail("Опыт не завершился")

    def test_every_pair_runs_and_measurements_stay_private(self):
        pairs = store.config()["model_pairs"]
        for name, expected in pairs.items():
            with self.subTest(pair=name):
                result, packets = self.run_trial(name)
                self.assertEqual(result["shift_final"], 2)
                self.assertEqual(sum(d["speaker"] == "attacker" for d in result["dialog"]), 4)
                self.assertEqual(result["attacker"]["id"], expected["attacker"])
                self.assertEqual(result["target"]["id"], expected["target"])
                for packet in packets:
                    if packet["fields"] is None:
                        self.assertFalse(any('"score"' in m["content"] for m in packet["messages"]))
        self.assertTrue(self.api_calls)

    def test_calibration_has_no_attacker_and_poll_selects_topic(self):
        for mode in ("bare", "neutral"):
            result, packets = self.run_trial("deepseek_to_codex", mode)
            self.assertTrue(all(p["actor"] == "target" for p in packets))
            self.assertNotIn("s_counter", result)
        ident = trial.start(mode="poll", target="codex_a")["id"]
        for _ in range(50):
            packet = trial.advance(ident)["request"]
            self.assertEqual(len(packet["messages"]), 1)
            trial.submit(ident, self.envelope(packet))
        self.assertTrue(trial.advance(ident)["done"])
        self.assertTrue(trial.selection_file("codex_a").exists())
        self.assertFalse(trial.selection_file("codex_b").exists())
        self.assertEqual(trial.spec(pair="deepseek_to_codex")["topic_source"], "poll")

    def test_submit_is_idempotent_and_checks_model_and_context(self):
        ident = trial.start(pair="codex_same", topic_id="topic_01")["id"]
        first = trial.advance(ident)["request"]
        answer = self.envelope(first)
        wrong = copy.deepcopy(answer)
        wrong["execution"]["model"] = "other-model"
        with self.assertRaises(ValueError):
            trial.submit(ident, wrong)
        trial.submit(ident, answer)
        trial.submit(ident, answer)
        changed = copy.deepcopy(answer)
        changed["content"] = "different response"
        with self.assertRaises(ValueError):
            trial.submit(ident, changed)
        second = trial.advance(ident)["request"]
        self.assertEqual(second, trial.advance(ident)["request"])
        reused = self.envelope(second)
        reused["execution"]["session_id"] = answer["execution"]["session_id"]
        with self.assertRaises(ValueError):
            trial.submit(ident, reused)
        self.assertEqual(trial.status(ident)["stage"], "pre")

    def test_three_zero_positions_skip_trial(self):
        ident = trial.start(pair="codex_same", topic_id="topic_01")["id"]
        for _ in range(3):
            trial.submit(ident, self.envelope(trial.advance(ident)["request"]))
            trial.submit(ident, self.envelope(trial.advance(ident)["request"], '{"score":0}'))
        self.assertEqual(trial.advance(ident)["stage"], "skipped")
        self.assertEqual(store.read_json(store.run_file("results", ident))["skipped"], "zero_position")

    def test_plans_share_control_and_keep_direction(self):
        cfg = store.config()
        cfg["model_pairs"]["reverse_versions"] = {"attacker": "codex_b", "target": "codex_a"}
        self.write_config(cfg)
        a = plan.make_plan("A", 0, ["codex_same"], "topic_01")["jobs"]
        b = plan.make_plan("B", 0, ["codex_same"], "topic_01")["jobs"]
        self.assertEqual((len(a), len(b)), (15, 6))
        self.assertEqual(a[0]["id"], b[0]["id"])
        m = plan.make_plan("M", 0, ["codex_versions", "reverse_versions"], "topic_01")["jobs"]
        self.assertNotEqual(m[0]["id"], m[1]["id"])
        calibration = plan.make_plan("calibration", 0, ["codex_same", "reverse_versions"], "topic_01")["jobs"]
        self.assertEqual(len(calibration), 2)
        pilot = plan.make_plan("pilot", 0, ["codex_same"], "topic_01")["jobs"]
        self.assertNotEqual(pilot[0]["id"], a[0]["id"])
        self.assertEqual(self.api_calls, [])

    def test_plan_reports_done_and_results_of_other_protocol(self):
        result, _ = self.run_trial("codex_same")
        job = plan.make_plan("M", 0, ["codex_same"], "topic_01")["jobs"][0]
        self.assertTrue(job["done"])
        self.assertEqual(job["earlier_results"], [])
        cfg = store.config()
        cfg["rounds"] = 3
        self.write_config(cfg)
        job = plan.make_plan("M", 0, ["codex_same"], "topic_01")["jobs"][0]
        self.assertFalse(job["done"])
        self.assertEqual(job["earlier_results"], [result["id"]])

    def test_protocol_ignores_profiles_but_not_dialogue_texts(self):
        before = store.protocol_digest()
        cfg = store.config()
        cfg["profiles"]["codex_b"]["model"] = "another-model"
        cfg["model_pairs"]["extra"] = {"attacker": "codex_b", "target": "deepseek"}
        self.write_config(cfg)
        self.assertEqual(store.protocol_digest(), before)
        path = self.root / "prompts/target_reply.txt"
        path.write_text(path.read_text(encoding="utf-8") + "\nЕщё одно требование.", encoding="utf-8")
        self.assertNotEqual(store.protocol_digest(), before)

    def test_invalid_input_fails_before_any_call(self):
        with self.assertRaises(ValueError):
            plan.make_plan("pilot", -1, ["codex_same"], "topic_01")
        with self.assertRaises(ValueError):
            trial.spec(pair="codex_same", target="codex_b", topic_id="topic_01")
        with self.assertRaises(ValueError):
            trial.spec(pair="codex_same", topic_id="unknown")
        with self.assertRaises(ValueError):
            trial.spec(pair="codex_same")  # опроса не было, тема не задана
        cfg = store.config()
        cfg["profiles"]["codex_a"]["model"] = None
        self.write_config(cfg)
        with self.assertRaises(ValueError):
            trial.start(pair="codex_same", topic_id="topic_01")
        self.assertEqual(self.api_calls, [])

    def test_invalid_api_answers_are_bounded_and_kept(self):
        self.patch(deepseek, "call", lambda model, scope, messages: "invalid JSON")
        ident = trial.start(mode="poll", target="deepseek")["id"]
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                trial.advance(ident)
            state = trial.load_state(ident)
            self.assertEqual(len(state["rejected"]), 3)
            self.assertEqual(state["poll_answers"], [])

    def test_attacker_instruction_renders_for_every_condition(self):
        for condition in prompts.conditions():
            for social in prompts.social_conditions():
                self.assertIn("Test topic", prompts.attacker_system("Test topic", condition, social, "за"))


class ApiCacheTests(unittest.TestCase):
    def test_cache_by_request_limit_and_stop(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        cfg = store.read_json(PROJECT / "config.json")
        cfg["api"]["max_requests"] = 2
        (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        sent = []

        class FakeClient:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=self)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def create(self, **kwargs):
                sent.append(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="response"))],
                                       usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 10}))

        messages = [{"role": "user", "content": "same question"}]
        with patch.object(store, "ROOT", root), \
             patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeClient)}), \
             patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-only"}):
            self.assertEqual(deepseek.call("deepseek", "request-1", messages), "response")
            deepseek.call("deepseek", "request-1", messages)
            self.assertEqual(len(sent), 1)
            deepseek.call("deepseek", "request-2", messages)
            self.assertEqual(len(sent), 2)
            with self.assertRaisesRegex(RuntimeError, "max_requests"):
                deepseek.call("deepseek", "request-3", messages)
            (root / "STOP").touch()
            with self.assertRaisesRegex(RuntimeError, "STOP"):
                deepseek.call("deepseek", "request-3", messages)


if __name__ == "__main__":
    unittest.main()
