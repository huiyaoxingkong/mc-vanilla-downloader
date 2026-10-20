import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd.netio import digest_matches, human_bytes, sha1_of_file  # noqa: E402


class TestHashing(unittest.TestCase):
    def test_sha1_and_digest_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            path.write_bytes(b"minecraft")
            expected = hashlib.sha1(b"minecraft").hexdigest()
            self.assertEqual(sha1_of_file(path), expected)
            self.assertTrue(digest_matches(path, expected, 9))
            self.assertFalse(digest_matches(path, expected, 10))
            self.assertFalse(digest_matches(path, "0" * 40, 9))
            self.assertFalse(digest_matches(Path(tmp) / "missing.bin", expected, 9))

    def test_digest_matches_without_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.bin"
            path.write_bytes(b"x" * 5)
            self.assertTrue(digest_matches(path, None, 5))
            self.assertFalse(digest_matches(path, None, 6))


class TestHumanBytes(unittest.TestCase):
    def test_units(self):
        self.assertEqual(human_bytes(512), "512 B")
        self.assertEqual(human_bytes(2048), "2.00 KB")
        self.assertEqual(human_bytes(5 * 1024 * 1024), "5.00 MB")


if __name__ == "__main__":
    unittest.main()
