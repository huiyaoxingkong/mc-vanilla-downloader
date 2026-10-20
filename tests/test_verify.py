import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd.installer import InstallOptions  # noqa: E402
from mcvd.mirrors import MIRROR_OFFICIAL  # noqa: E402
from mcvd.verify import (  # noqa: E402
    all_versions,
    collect_tasks,
    format_report,
    verify_version,
    version_chain,
)


def make_options(root: Path) -> InstallOptions:
    return InstallOptions(mc_dir=root, mirror=MIRROR_OFFICIAL, quiet=True)


def write(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def build_fake_install(root: Path) -> None:
    client_bytes = b"client-jar"
    lib_bytes = b"library-jar"
    asset_bytes = b"asset-data"

    client_sha = hashlib.sha1(client_bytes).hexdigest()
    lib_sha = hashlib.sha1(lib_bytes).hexdigest()
    asset_sha = hashlib.sha1(asset_bytes).hexdigest()

    index_bytes = json.dumps(
        {"objects": {"demo/texture.png": {"hash": asset_sha, "size": len(asset_bytes)}}}
    ).encode("utf-8")
    index_sha = hashlib.sha1(index_bytes).hexdigest()

    versions = root / "versions" / "1.0"
    versions.mkdir(parents=True)
    payload = {
        "id": "1.0",
        "downloads": {"client": {"url": "https://example/client.jar", "sha1": client_sha, "size": len(client_bytes)}},
        "libraries": [
            {
                "name": "org.example:demo:1.0",
                "downloads": {
                    "artifact": {
                        "path": "org/example/demo/1.0/demo-1.0.jar",
                        "url": "https://example/demo.jar",
                        "sha1": lib_sha,
                        "size": len(lib_bytes),
                    }
                },
            }
        ],
        "assetIndex": {"id": "3", "url": "https://example/3.json", "sha1": index_sha, "size": len(index_bytes)},
    }
    (versions / "1.0.json").write_text(json.dumps(payload), encoding="utf-8")
    (versions / "1.0.jar").write_bytes(client_bytes)

    lib = root / "libraries" / "org" / "example" / "demo" / "1.0" / "demo-1.0.jar"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(lib_bytes)

    (root / "assets" / "indexes").mkdir(parents=True)
    (root / "assets" / "indexes" / "3.json").write_bytes(index_bytes)
    asset = root / "assets" / "objects" / asset_sha[:2] / asset_sha
    asset.parent.mkdir(parents=True)
    asset.write_bytes(asset_bytes)


class TestVerify(unittest.TestCase):
    def test_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fake_install(root)
            report = verify_version("1.0", root, make_options(root))
            self.assertTrue(report.healthy, report.problems)
            self.assertEqual(report.checked, 4)  # client + lib + index + asset

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fake_install(root)
            (root / "versions" / "1.0" / "1.0.jar").unlink()
            report = verify_version("1.0", root, make_options(root))
            self.assertFalse(report.healthy)
            self.assertEqual(len(report.missing), 1)
            self.assertIn("client", report.missing[0])

    def test_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fake_install(root)
            (root / "versions" / "1.0" / "1.0.jar").write_bytes(b"broken")
            report = verify_version("1.0", root, make_options(root))
            self.assertFalse(report.healthy)
            self.assertEqual(len(report.corrupt), 1)
            self.assertEqual(len(report.broken_tasks), 1)

    def test_missing_index_noted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fake_install(root)
            (root / "assets" / "indexes" / "3.json").unlink()
            report = verify_version("1.0", root, make_options(root))
            self.assertTrue(any("资源索引" in note for note in report.notes))

    def test_inherits_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fake_install(root)
            loader_dir = root / "versions" / "fabric-loader"
            loader_dir.mkdir()
            (loader_dir / "fabric-loader.json").write_text(
                json.dumps({"id": "fabric-loader", "inheritsFrom": "1.0", "libraries": []}),
                encoding="utf-8",
            )
            chain, notes = version_chain("fabric-loader", root)
            self.assertEqual([item[0] for item in chain], ["fabric-loader", "1.0"])
            tasks, _ = collect_tasks("fabric-loader", root, make_options(root))
            self.assertGreaterEqual(len(tasks), 3)
            report = verify_version("fabric-loader", root, make_options(root))
            self.assertTrue(report.healthy, report.problems)

    def test_missing_version_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = verify_version("nope", Path(tmp), make_options(Path(tmp)))
            self.assertFalse(report.healthy)
            self.assertTrue(report.notes)

    def test_all_versions_and_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fake_install(root)
            self.assertEqual(all_versions(root), ["1.0"])
            report = verify_version("1.0", root, make_options(root))
            text = format_report(report)
            self.assertIn("1.0", text)
            self.assertIn("完整", text)


if __name__ == "__main__":
    unittest.main()
