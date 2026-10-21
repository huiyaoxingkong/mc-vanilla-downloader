import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd import compat, saves  # noqa: E402


def make_save(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "level.dat").write_bytes(b"level")


def build_mc(root: Path) -> None:
    make_save(root / "saves" / "全局存档")
    version = root / "versions" / "1.20.1-forge"
    version.mkdir(parents=True)
    (version / "1.20.1-forge.json").write_text('{"id": "1.20.1-forge"}', encoding="utf-8")
    make_save(version / "saves" / "隔离存档")


class TestSaves(unittest.TestCase):
    def test_discover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_mc(root)
            items = saves.discover_saves(root, with_size=False)
            self.assertEqual(len(items), 2)
            isolated = [item for item in items if item.isolated]
            self.assertEqual(len(isolated), 1)
            self.assertEqual(isolated[0].version, "1.20.1-forge")
            self.assertEqual(isolated[0].name, "隔离存档")

    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_mc(root)
            summary = saves.save_summary(root)
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["isolated"], 1)
            self.assertEqual(summary["global"], 1)
            self.assertEqual(summary["versions"], ["1.20.1-forge"])

    def test_register_isolated_save_writes_game_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_mc(root)
            isolated = [item for item in saves.discover_saves(root, with_size=False) if item.isolated][0]
            saves.register_save(root, isolated)
            payload = json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))
            entry = next(iter(payload["profiles"].values()))
            self.assertEqual(entry["lastVersionId"], "1.20.1-forge")
            self.assertTrue(entry["gameDir"].endswith("versions\\1.20.1-forge") or entry["gameDir"].endswith("versions/1.20.1-forge"))
            self.assertIn("隔离存档", entry["name"])

    def test_register_global_save_has_no_game_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_mc(root)
            global_save = [item for item in saves.discover_saves(root, with_size=False) if not item.isolated][0]
            saves.register_save(root, global_save)
            payload = json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))
            entry = next(iter(payload["profiles"].values()))
            self.assertNotIn("gameDir", entry)

    def test_register_all_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_mc(root)
            other = root / "versions" / "1.21.4-fabric"
            other.mkdir(parents=True)
            (other / "1.21.4-fabric.json").write_text("{}", encoding="utf-8")
            make_save(other / "saves" / "另一个存档")
            count = saves.register_all_isolated(root)
            self.assertEqual(count, 2)
            profiles = compat.official_profile_entries(root)
            self.assertEqual(len(profiles), 2)
            self.assertTrue(all("gameDir" in entry for entry in profiles))

    def test_version_save_registration_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_mc(root)
            isolated = [item for item in saves.discover_saves(root, with_size=False) if item.isolated][0]
            first = saves.register_save(root, isolated)
            second = saves.register_save(root, isolated)
            self.assertEqual(first, second)
            payload = json.loads((root / "launcher_profiles.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["profiles"]), 1)


if __name__ == "__main__":
    unittest.main()
