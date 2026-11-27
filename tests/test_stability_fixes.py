import json
import os
import tempfile
import unittest

import numpy as np

from jobs import DocIndex
from self_healing_agent import SelfHealingAgent


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

    def test_mismatched_legacy_pair_starts_empty(self):
        with open(self.base + ".json", "w", encoding="utf-8") as stream:
            json.dump([{"src": "orphan.txt", "text": "no matching vector"}], stream)
        np.save(self.base + ".npy", np.zeros((0, 2), dtype=np.float32))

        loaded = DocIndex(self.base)

        self.assertEqual(loaded.items, [])
        self.assertEqual(loaded.vecs.shape, (0, 1))


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
