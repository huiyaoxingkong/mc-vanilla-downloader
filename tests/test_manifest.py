import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd.manifest import VersionNotFound, filter_versions, pick_version  # noqa: E402

MANIFEST = {
    "latest": {"release": "26.3", "snapshot": "26.4-snapshot-5"},
    "versions": [
        {"id": "26.4-snapshot-5", "type": "snapshot", "url": "https://example/snap.json"},
        {"id": "26.3", "type": "release", "url": "https://example/26.3.json"},
        {"id": "26.2", "type": "release", "url": "https://example/26.2.json"},
        {"id": "Beta 1.7.3", "type": "old_beta", "url": "https://example/beta.json"},
    ],
}


class TestManifest(unittest.TestCase):
    def test_pick_latest(self):
        self.assertEqual(pick_version(MANIFEST, "latest")["id"], "26.3")
        self.assertEqual(pick_version(MANIFEST, "最新")["id"], "26.3")

    def test_pick_latest_snapshot(self):
        self.assertEqual(pick_version(MANIFEST, "latest-snapshot")["id"], "26.4-snapshot-5")
        self.assertEqual(pick_version(MANIFEST, "快照")["id"], "26.4-snapshot-5")

    def test_pick_exact(self):
        self.assertEqual(pick_version(MANIFEST, "26.2")["id"], "26.2")
        self.assertEqual(pick_version(MANIFEST, "26.2 ")["id"], "26.2")

    def test_pick_case_insensitive(self):
        self.assertEqual(pick_version(MANIFEST, "beta 1.7.3")["id"], "Beta 1.7.3")

    def test_pick_missing(self):
        with self.assertRaises(VersionNotFound):
            pick_version(MANIFEST, "9.9.9")

    def test_filter(self):
        self.assertEqual([v["id"] for v in filter_versions(MANIFEST, "release")], ["26.3", "26.2"])
        self.assertEqual(len(filter_versions(MANIFEST, "snapshot")), 1)
        self.assertEqual(len(filter_versions(MANIFEST, "all")), 4)
        self.assertEqual(len(filter_versions(MANIFEST, "all", limit=2)), 2)
        with self.assertRaises(ValueError):
            filter_versions(MANIFEST, "nope")


if __name__ == "__main__":
    unittest.main()
