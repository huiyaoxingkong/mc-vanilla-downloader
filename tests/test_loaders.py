import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd import java as _java  # noqa: E402
from mcvd import loaders  # noqa: E402


class TestJavaRequirement(unittest.TestCase):
    def test_modern_versions(self):
        self.assertEqual(_java.required_major("1.21.4"), 21)
        self.assertEqual(_java.required_major("1.20.1"), 17)
        self.assertEqual(_java.required_major("1.18.2"), 17)
        self.assertEqual(_java.required_major("1.16.5"), 8)
        self.assertEqual(_java.required_major("1.12.2"), 8)
        self.assertEqual(_java.required_major("26.3"), 25)

    def test_garbage(self):
        self.assertEqual(_java.required_major("not-a-version"), 17)


class TestLoaderHelpers(unittest.TestCase):
    def test_neoforge_game_version(self):
        self.assertEqual(loaders.neoforge_game_version("21.1.72"), "1.21.1")
        self.assertEqual(loaders.neoforge_game_version("20.4.237"), "1.20.4")
        self.assertEqual(loaders.neoforge_game_version("bad"), "")

    def test_rename_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "versions" / "1.20.1-forge-47.2.0"
            old.mkdir(parents=True)
            (old / "1.20.1-forge-47.2.0.json").write_text(
                '{"id": "1.20.1-forge-47.2.0", "libraries": []}', encoding="utf-8"
            )
            (old / "mcvd-install.json").write_text('{"version": "1.20.1-forge-47.2.0"}', encoding="utf-8")
            loaders.rename_version(root, "1.20.1-forge-47.2.0", "我的整合包")
            new = root / "versions" / "我的整合包"
            self.assertTrue((new / "我的整合包.json").is_file())
            self.assertFalse((new / "1.20.1-forge-47.2.0.json").exists())
            self.assertIn('"id": "我的整合包"', (new / "我的整合包.json").read_text(encoding="utf-8"))

    def test_rename_target_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "versions" / "a").mkdir(parents=True)
            (root / "versions" / "b").mkdir(parents=True)
            with self.assertRaises(Exception):
                loaders.rename_version(root, "a", "b")

    def test_supported_loaders(self):
        self.assertEqual(loaders.loader_choices(), ["fabric", "quilt", "forge", "neoforge"])


if __name__ == "__main__":
    unittest.main()
