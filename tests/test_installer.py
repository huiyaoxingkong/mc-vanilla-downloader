import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd.installer import (  # noqa: E402
    InstallOptions,
    build_asset_tasks,
    build_client_task,
    build_library_tasks,
    library_entries,
    maven_path,
)
from mcvd.mirrors import MIRROR_OFFICIAL  # noqa: E402


def make_options(root: Path) -> InstallOptions:
    return InstallOptions(mc_dir=root, mirror=MIRROR_OFFICIAL)


class TestMavenPath(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(
            maven_path("org.lwjgl:lwjgl:3.3.3"),
            "org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar",
        )

    def test_classifier(self):
        self.assertEqual(
            maven_path("org.lwjgl:lwjgl:3.3.3:natives-windows"),
            "org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3-natives-windows.jar",
        )

    def test_extension(self):
        self.assertEqual(
            maven_path("net.minecraft:client:1.0@zip"),
            "net/minecraft/client/1.0/client-1.0.zip",
        )

    def test_invalid(self):
        with self.assertRaises(ValueError):
            maven_path("broken")


class TestLibraryEntries(unittest.TestCase):
    def test_plain_library(self):
        lib = {
            "name": "org.lwjgl:lwjgl:3.3.3",
            "downloads": {"artifact": {"path": "org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar", "url": "https://libraries.minecraft.net/x", "sha1": "abc"}},
        }
        entries = library_entries(lib, "windows", "x86_64")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["sha1"], "abc")

    def test_skipped_by_rules(self):
        lib = {
            "name": "test:test:1",
            "rules": [{"action": "allow", "os": {"name": "osx"}}],
            "downloads": {"artifact": {"path": "test/test/1/test-1.jar", "url": "https://libraries.minecraft.net/x"}},
        }
        self.assertEqual(library_entries(lib, "windows", "x86_64"), [])

    def test_natives_classifier(self):
        lib = {
            "name": "org.lwjgl:lwjgl:2.9.4",
            "natives": {"windows": "natives-windows-${arch}"},
            "downloads": {
                "classifiers": {
                    "natives-windows-64": {"path": "org/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4-natives-windows.jar", "url": "https://libraries.minecraft.net/n"},
                }
            },
        }
        entries = library_entries(lib, "windows", "x86_64")
        self.assertEqual(len(entries), 1)
        self.assertIn("natives-windows", entries[0]["path"])


class TestTasks(unittest.TestCase):
    def test_build_library_task_paths(self):
        version_json = {
            "libraries": [
                {
                    "name": "com.example:demo:1.0",
                    "downloads": {"artifact": {"url": "https://libraries.minecraft.net/com/example/demo/1.0/demo-1.0.jar", "sha1": "s", "size": 10}},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            tasks = build_library_tasks(version_json, Path(tmp), make_options(Path(tmp)))
            self.assertEqual(len(tasks), 1)
            self.assertTrue(str(tasks[0].dest).replace("\\", "/").endswith("libraries/com/example/demo/1.0/demo-1.0.jar"))

    def test_build_asset_tasks(self):
        index = {"objects": {"icons/icon.png": {"hash": "abcdef0123", "size": 100}}}
        with tempfile.TemporaryDirectory() as tmp:
            tasks = build_asset_tasks(index, Path(tmp), make_options(Path(tmp)))
            self.assertEqual(len(tasks), 1)
            self.assertTrue(str(tasks[0].dest).replace("\\", "/").endswith("assets/objects/ab/abcdef0123"))
            self.assertEqual(tasks[0].sha1, "abcdef0123")
            self.assertEqual(
                tasks[0].urls[0],
                "https://resources.download.minecraft.net/ab/abcdef0123",
            )

    def test_build_client_task(self):
        version_json = {"downloads": {"client": {"url": "https://piston-data.mojang.com/v1/objects/aa/client.jar", "sha1": "x", "size": 1}}}
        with tempfile.TemporaryDirectory() as tmp:
            task = build_client_task(version_json, "1.2.3", Path(tmp), make_options(Path(tmp)))
            self.assertTrue(str(task.dest).replace("\\", "/").endswith("versions/1.2.3/1.2.3.jar"))

    def test_build_asset_tasks_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(build_asset_tasks({}, Path(tmp), make_options(Path(tmp))), [])


if __name__ == "__main__":
    unittest.main()
