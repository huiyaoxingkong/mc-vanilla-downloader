import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd.rules import is_allowed  # noqa: E402


class TestRules(unittest.TestCase):
    def test_no_rules_allowed(self):
        self.assertTrue(is_allowed(None, "windows", "x86_64"))
        self.assertTrue(is_allowed([], "windows", "x86_64"))

    def test_allow_windows_only(self):
        rules = [{"action": "allow", "os": {"name": "windows"}}]
        self.assertTrue(is_allowed(rules, "windows", "x86_64"))
        self.assertFalse(is_allowed(rules, "linux", "x86_64"))

    def test_disallow_block_after_allow(self):
        rules = [
            {"action": "allow"},
            {"action": "disallow", "os": {"name": "osx"}},
        ]
        self.assertTrue(is_allowed(rules, "windows", "x86_64"))
        self.assertFalse(is_allowed(rules, "osx", "arm64"))

    def test_arch_rule(self):
        rules = [{"action": "allow", "os": {"name": "windows", "arch": "x86"}}]
        self.assertFalse(is_allowed(rules, "windows", "x86_64"))
        self.assertTrue(is_allowed(rules, "windows", "x86"))

    def test_features_rule_disabled(self):
        # 原版库里 features 只用于 demo / custom_resolution，一律按未启用处理
        rules = [{"action": "allow", "features": {"is_demo_user": True}}]
        self.assertFalse(is_allowed(rules, "windows", "x86_64"))


if __name__ == "__main__":
    unittest.main()
