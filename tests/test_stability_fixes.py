import json
import os
import tempfile
import unittest

import numpy as np


class UnsafePicklePayload:
    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return exec, (f"open({self.marker!r}, 'w', encoding='utf-8').write('ran')",)

from jobs import DocIndex
from self_healing_agent import SelfHealingAgent
from code_executor import solve as solve_generated_code
from download_agent import _validate_public_download_url
from safe_pickle import atomic_bytes_write, atomic_json_write, atomic_text_write, load_numpy_pickle
from screen_agent import risk_reason as screen_risk_reason
from phone_screen_agent import risk_reason as phone_risk_reason
from voice_activation_agent import VoiceRecognitionAgent
from jarvis_ui import claim_instance
from plugin_manager import PluginManager
import planner_agent


class DocIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.temp_dir.name, "documents")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_snapshot_round_trip(self):
        index = DocIndex(self.base)
        index.items = [{"src": "notes.txt", "text": "physics notes"}]
        index.vecs = np.asarray([[0.1, 0.2, 0.3]], dtype=np.float32)

        index.save()
        loaded = DocIndex(self.base)

        self.assertEqual(loaded.items, index.items)
        np.testing.assert_allclose(loaded.vecs, index.vecs)
        self.assertTrue(os.path.isfile(self.base + ".npz"))

    def test_corrupt_snapshot_recovers_legacy_pair(self):
        with open(self.base + ".npz", "wb") as stream:
            stream.write(b"not a zip archive")
        legacy_items = [{"src": "legacy.txt", "text": "older index"}]
        with open(self.base + ".json", "w", encoding="utf-8") as stream:
            json.dump(legacy_items, stream)
        np.save(self.base + ".npy", np.asarray([[1.0, 0.0]], dtype=np.float32))

        loaded = DocIndex(self.base)

        self.assertEqual(loaded.items, legacy_items)
        np.testing.assert_allclose(loaded.vecs, [[1.0, 0.0]])

    def test_add_rejects_dimension_mismatch_without_losing_existing_source(self):
        index = DocIndex(self.base)
        index.items = [{"src": "old.txt", "text": "keep me"}]
        index.vecs = np.asarray([[1.0, 0.0]], dtype=np.float32)

        added = index.add("new.txt", ["new content"], [[0.1, 0.2, 0.3]])

        self.assertEqual(added, 0)
        self.assertEqual(index.items, [{"src": "old.txt", "text": "keep me"}])
        np.testing.assert_allclose(index.vecs, [[1.0, 0.0]])

    def test_search_rejects_wrong_vector_dimensions(self):
        index = DocIndex(self.base)
        index.items = [{"src": "old.txt", "text": "keep me"}]
        index.vecs = np.asarray([[1.0, 0.0]], dtype=np.float32)

        self.assertEqual(index.search([1.0, 0.0, 0.0]), [])

    def test_mismatched_legacy_pair_starts_empty(self):
        with open(self.base + ".json", "w", encoding="utf-8") as stream:
            json.dump([{"src": "orphan.txt", "text": "no matching vector"}], stream)
        np.save(self.base + ".npy", np.zeros((0, 2), dtype=np.float32))

        loaded = DocIndex(self.base)

        self.assertEqual(loaded.items, [])
        self.assertEqual(loaded.vecs.shape, (0, 1))


class SafePickleTests(unittest.TestCase):
    def test_atomic_json_profile_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "profile.json")
            expected = {"features": [0.1, 0.2], "lock": True}

            atomic_json_write(path, expected)

            with open(path, "r", encoding="utf-8") as stream:
                self.assertEqual(json.load(stream), expected)

    def test_atomic_text_and_binary_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = os.path.join(directory, "note.txt")
            bytes_path = os.path.join(directory, "secret.bin")

            atomic_text_write(text_path, "Jarvis state")
            atomic_bytes_write(bytes_path, b"encrypted")

            with open(text_path, "r", encoding="utf-8") as stream:
                self.assertEqual(stream.read(), "Jarvis state")
            with open(bytes_path, "rb") as stream:
                self.assertEqual(stream.read(), b"encrypted")

    def test_numpy_pickle_round_trip_remains_supported(self):
        import pickle

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "profile.pkl")
            expected = {"features": np.asarray([0.1, 0.2], dtype=np.float32), "lock": True}
            with open(path, "wb") as stream:
                pickle.dump(expected, stream)

            actual = load_numpy_pickle(path, max_bytes=100_000)

            self.assertTrue(actual["lock"])
            np.testing.assert_allclose(actual["features"], expected["features"])

    def test_untrusted_global_is_rejected(self):
        import pickle

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "untrusted.pkl")
            with open(path, "wb") as stream:
                pickle.dump(UnsafePicklePayload(os.path.join(directory, "executed.txt")), stream)

            with self.assertRaises(pickle.UnpicklingError):
                load_numpy_pickle(path, max_bytes=100_000)
            self.assertFalse(os.path.exists(os.path.join(directory, "executed.txt")))


class DownloadSafetyTests(unittest.TestCase):
    def test_local_and_private_pdf_urls_are_rejected(self):
        for url in ("http://localhost/file.pdf", "http://127.0.0.1/file.pdf",
                    "http://192.168.1.10/file.pdf", "http://10.0.0.1/file.pdf"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_public_download_url(url)

    def test_domain_resolving_to_private_address_is_rejected(self):
        from unittest.mock import patch

        result = (None, None, None, None, ("10.0.0.8", 0))
        with patch("download_agent.socket.getaddrinfo", return_value=[result]):
            with self.assertRaises(ValueError):
                _validate_public_download_url("https://private.example/file.pdf")


class PlannerCodeApprovalTests(unittest.TestCase):
    def test_planner_hides_python_tool_without_approval(self):
        self.assertNotIn('"run_python"', planner_agent._tool_list(allow_code=False))
        self.assertIn('"run_python"', planner_agent._tool_list(allow_code=True))

    def test_planner_python_tool_refuses_without_context_approval(self):
        with self.assertRaisesRegex(RuntimeError, "not approved"):
            planner_agent._run_python("print('no')", {"goal": "summarize a topic"})


class PluginLoadSafetyTests(unittest.TestCase):
    def test_top_level_executable_code_is_rejected_before_import(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as plugin_dir:
            marker = os.path.join(plugin_dir, "executed.txt")
            path = os.path.join(plugin_dir, "unsafe_plugin.py")
            source = (
                "import re\n"
                f"open({marker!r}, 'w', encoding='utf-8').write('ran')\n"
                "META = {'name': 'unsafe', 'triggers': ['unsafe']}\n"
                "def run(ctx, command, match):\n    return 'unsafe'\n"
            )
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(source)
            with patch("plugin_manager.PLUGIN_DIR", plugin_dir):
                manager = PluginManager({})
                ok, reason = manager.load_one(path)

            self.assertFalse(ok)
            self.assertIn("unsupported top-level statement", reason)
            self.assertFalse(os.path.exists(marker))

    def test_existing_phone_notifications_plugin_is_allowed(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins", "phone_notifications.py")
        valid, reason = __import__("plugin_manager")._validate_plugin_source(path)
        self.assertTrue(valid, reason)


class SingleInstanceTests(unittest.TestCase):
    def test_bind_conflict_without_jarvis_listener_is_not_silently_accepted(self):
        from unittest.mock import patch

        with patch("jarvis_ui.socket.socket") as socket_factory, patch(
                "jarvis_ui.socket.create_connection", side_effect=ConnectionRefusedError):
            fake_socket = socket_factory.return_value
            fake_socket.bind.side_effect = OSError("address already in use")

            with self.assertRaisesRegex(RuntimeError, "no running Jarvis instance"):
                claim_instance(lambda: None)

            fake_socket.close.assert_called_once()


class CodeExecutionSafetyTests(unittest.TestCase):
    def test_execution_is_refused_without_explicit_approval(self):
        result = solve_generated_code("print('hello')")

        self.assertFalse(result.ok)
        self.assertEqual(result.attempts, 0)
        self.assertIn("no code was run", result.stderr)


class VoiceLockTests(unittest.TestCase):
    def test_enabled_lock_rejects_when_model_is_unavailable(self):
        agent = VoiceRecognitionAgent()
        agent._lock_on = True
        agent.known_features = np.ones(256, dtype=np.float32)
        agent._avail = False

        accepted, score, note = agent.check(np.zeros(16000, dtype=np.float32))

        self.assertFalse(accepted)
        self.assertIsNone(score)
        self.assertIn("rejected", note)


class ScreenActionSafetyTests(unittest.TestCase):
    def test_screen_enter_after_typing_requires_confirmation(self):
        reason = screen_risk_reason({"action": "press", "key": "enter"}, [], ['typed "hello"'])
        self.assertIn("submitting", reason)

    def test_phone_enter_in_editable_field_requires_confirmation(self):
        state = {"field": {"editable": True, "label": "Message"}}
        reason = phone_risk_reason({"action": "key", "key": "enter"}, [], state)
        self.assertIn("submitting", reason)

    def test_phone_tap_after_typing_requires_confirmation(self):
        history = ['typed "hello"']
        reason = phone_risk_reason({"action": "tap", "id": 3}, [], {}, history)
        self.assertIn("confirming", reason)

    def test_enter_without_recent_text_is_not_flagged(self):
        self.assertIsNone(screen_risk_reason({"action": "press", "key": "enter"}, [], []))
        self.assertIsNone(phone_risk_reason({"action": "key", "key": "enter"}, [], {}, []))


class SelfHealingPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "sample.py")
        self.original = "value = 1\n"
        self.patched = "value = 2\n"
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write(self.original)
        self.agent = SelfHealingAgent()
        self.agent.pending_patch = (self.path, self.original, self.patched)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_apply_is_atomic_and_keeps_backup(self):
        ok, _ = self.agent.apply_pending_patch()

        self.assertTrue(ok)
        with open(self.path, "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), self.patched)
        with open(self.path + ".bak", "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), self.original)
        self.assertIsNone(self.agent.pending_patch)

    def test_refuses_to_overwrite_newer_source(self):
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("value = 3\n")

        ok, message = self.agent.apply_pending_patch()

        self.assertFalse(ok)
        self.assertIn("changed after the patch was staged", message)
        with open(self.path, "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "value = 3\n")


if __name__ == "__main__":
    unittest.main()
