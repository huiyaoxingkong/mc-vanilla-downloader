import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd import compat  # noqa: E402


class TestOfficialProfiles(unittest.TestCase):
    def test_create_and_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compat.register_official_profile(root, "1.21.4", display_name="原版生存")
            payload = json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 6)
            self.assertEqual(len(payload["profiles"]), 1)
            entry = next(iter(payload["profiles"].values()))
            self.assertEqual(entry["lastVersionId"], "1.21.4")
            self.assertEqual(entry["name"], "原版生存")
            self.assertEqual(entry["type"], "custom")
            self.assertIn("created", entry)
            self.assertIn("lastUsed", entry)
            self.assertTrue(compat.has_official_profile(root, "1.21.4"))
            self.assertFalse(compat.has_official_profile(root, "1.20.1"))

    def test_register_twice_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = compat.register_official_profile(root, "1.21.4")
            second = compat.register_official_profile(root, "1.21.4")
            self.assertEqual(first, second)
            payload = json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["profiles"]), 1)

    def test_preserves_existing_profiles_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = {
                "profiles": {"abc": {"name": "latest-release", "lastVersionId": "latest-release", "type": "latest-release"}},
                "settings": {"enableSnapshots": True},
                "version": 6,
            }
            (root / "launcher_profiles.json").write_text(json.dumps(existing), encoding="utf-8")
            compat.register_official_profile(root, "1.20.1")
            payload = json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))
            self.assertIn("abc", payload["profiles"])
            self.assertTrue(payload["settings"]["enableSnapshots"])
            self.assertEqual(len(payload["profiles"]), 2)

    def test_ensure_creates_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mc"
            compat.ensure_official_launcher_profiles(root)
            payload = json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["profiles"], {})
            self.assertIn("settings", payload)

    def test_ensure_keeps_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "launcher_profiles.json").write_text('{"profiles": {"x": 1}}', encoding="utf-8")
            compat.ensure_official_launcher_profiles(root)
            self.assertEqual(
                json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))["profiles"],
                {"x": 1},
            )


class TestLauncherDetection(unittest.TestCase):
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = compat.detect_launchers(Path(tmp))
            present = [item.name for item in items if item.present]
            self.assertEqual(present, [])
            self.assertIn("未检测到", compat.describe_launchers(Path(tmp)))

    def test_pcl_hmcl_official(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PCL").mkdir()
            (root / "PCL" / "Setup.ini").write_text("LaunchArgumentIndieV2:4\n", encoding="utf-8")
            (root / "hmcl.json").write_text(json.dumps({"versionIsolation": False}), encoding="utf-8")
            compat.register_official_profile(root, "1.21.4")
            items = compat.detect_launchers(root)
            keys = {item.key: item for item in items}
            self.assertTrue(keys["pcl"].present)
            self.assertTrue(keys["hmcl"].present)
            self.assertTrue(keys["official"].present)
            self.assertIn("1 个配置", keys["official"].detail)
            text = compat.describe_launchers(root)
            self.assertIn("PCL", text)
            self.assertIn("HMCL", text)

    def test_hmcl_legacy_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "hmcl.json").write_text(json.dumps({"versionIsolation": True, "uiVersion": 0}), encoding="utf-8")
            settings = compat.read_hmcl_settings(root)
            self.assertIs(settings["versionIsolation"], True)
            self.assertEqual(settings["_source"], "hmcl.json")


if __name__ == "__main__":
    unittest.main()
