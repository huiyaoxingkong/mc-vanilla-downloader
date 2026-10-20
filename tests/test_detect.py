import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd import detect  # noqa: E402


class TestInspect(unittest.TestCase):
    def test_missing_dir(self):
        info = detect.inspect(Path(tempfile.gettempdir()) / "definitely-not-here-xyz", with_size=False, with_java=False)
        self.assertFalse(info.exists)
        self.assertIn("不存在", detect.describe(info))

    def test_plain_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = detect.inspect(Path(tmp), with_size=False, with_java=False)
            self.assertTrue(info.exists)
            self.assertFalse(info.is_minecraft)
            self.assertIn("还不是 Minecraft", detect.describe(info))

    def test_minecraft_dir_with_pcl_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = root / "versions" / "1.21.4"
            version.mkdir(parents=True)
            (version / "1.21.4.json").write_text('{"id": "1.21.4"}', encoding="utf-8")
            (root / "assets").mkdir()
            (root / "launcher_profiles.json").write_text("{}", encoding="utf-8")
            detect.write_ini(root / "PCL" / "Setup.ini", {"LaunchArgumentIndieV2": "4"})

            info = detect.inspect(root, with_size=False, with_java=False)
            self.assertTrue(info.is_minecraft)
            self.assertTrue(info.pcl_portable)
            self.assertEqual(info.global_isolation, 4)
            self.assertEqual(info.global_isolation_text, "隔离所有版本")
            self.assertEqual([v.name for v in info.versions], ["1.21.4"])
            self.assertIsNone(info.versions[0].isolated)

    def test_version_isolation_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = root / "versions" / "1.20.1-forge"
            version.mkdir(parents=True)
            (version / "1.20.1-forge.json").write_text("{}", encoding="utf-8")
            detect.write_ini(version / "PCL" / "Setup.ini", {"VersionArgumentIndieV2": "True"})
            info = detect.inspect(root, with_size=False, with_java=False)
            self.assertTrue(info.versions[0].isolated)
            self.assertIn("已开启", detect.describe(info))

    def test_auto_isolation_by_mods(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version = root / "versions" / "1.16.5"
            (version / "mods").mkdir(parents=True)
            (version / "1.16.5.json").write_text("{}", encoding="utf-8")
            (version / "mods" / "a.jar").write_bytes(b"x")
            info = detect.inspect(root, with_size=False, with_java=False)
            self.assertTrue(info.versions[0].isolated)
            self.assertIn("自动判定", info.versions[0].reason)


class TestCreate(unittest.TestCase):
    def test_create_structure_and_pcl_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = detect.create_mc_dir(Path(tmp), ".minecraft", isolation=1)
            self.assertTrue((target / "versions").is_dir())
            self.assertTrue((target / "assets").is_dir())
            self.assertTrue((target / "libraries").is_dir())
            self.assertTrue((target / "launcher_profiles.json").is_file())
            values = detect.read_ini(target / "PCL" / "Setup.ini")
            self.assertEqual(values["LaunchArgumentIndieV2"], "1")

            info = detect.inspect(target, with_size=False, with_java=False)
            self.assertEqual(info.global_isolation, 1)

    def test_create_refuses_non_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            (parent / "mc").mkdir()
            (parent / "mc" / "keep.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                detect.create_mc_dir(parent, "mc")

    def test_create_without_pcl_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = detect.create_mc_dir(Path(tmp), "game", write_pcl=False)
            self.assertFalse((target / "PCL").exists())

    def test_isolation_choices(self):
        values = [value for value, _label, _desc in detect.ISOLATION_CHOICES]
        self.assertEqual(values, [0, 1, 2, 3, 4])
        self.assertEqual(detect.ISOLATION_TEXT[4], "隔离所有版本")


if __name__ == "__main__":
    unittest.main()
