import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcvd import mirrors  # noqa: E402


class TestMirrorRewrite(unittest.TestCase):
    def test_bmclapi_manifest(self):
        self.assertEqual(
            mirrors.MIRROR_BMCLAPI.manifest_url(),
            "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
        )

    def test_official_manifest(self):
        self.assertEqual(mirrors.MIRROR_OFFICIAL.manifest_url(), mirrors.OFFICIAL_MANIFEST_URL)

    def test_version_json_same_path(self):
        url = "https://piston-meta.mojang.com/v1/packages/61fff1/26.3.json"
        self.assertEqual(
            mirrors.MIRROR_BMCLAPI.rewrite(url),
            "https://bmclapi2.bangbang93.com/v1/packages/61fff1/26.3.json",
        )

    def test_client_jar_same_path(self):
        url = "https://piston-data.mojang.com/v1/objects/e877b6/client.jar"
        self.assertEqual(
            mirrors.MIRROR_BMCLAPI.rewrite(url),
            "https://bmclapi2.bangbang93.com/v1/objects/e877b6/client.jar",
        )

    def test_libraries_to_maven(self):
        url = "https://libraries.minecraft.net/org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar"
        self.assertEqual(
            mirrors.MIRROR_BMCLAPI.rewrite(url),
            "https://bmclapi2.bangbang93.com/maven/org/lwjgl/lwjgl/3.3.3/lwjgl-3.3.3.jar",
        )

    def test_assets_to_assets_prefix(self):
        url = "https://resources.download.minecraft.net/ab/abcdef0123456789"
        self.assertEqual(
            mirrors.MIRROR_BMCLAPI.rewrite(url),
            "https://bmclapi2.bangbang93.com/assets/ab/abcdef0123456789",
        )

    def test_official_passthrough(self):
        url = "https://piston-data.mojang.com/v1/objects/e877b6/client.jar"
        self.assertEqual(mirrors.MIRROR_OFFICIAL.rewrite(url), url)

    def test_unknown_host_passthrough(self):
        url = "https://example.com/some/file.jar"
        self.assertEqual(mirrors.MIRROR_BMCLAPI.rewrite(url), url)

    def test_get_mirror_aliases(self):
        self.assertIs(mirrors.get_mirror("bmcl"), mirrors.MIRROR_BMCLAPI)
        self.assertIs(mirrors.get_mirror("OFFICIAL"), mirrors.MIRROR_OFFICIAL)
        with self.assertRaises(KeyError):
            mirrors.get_mirror("nope")


if __name__ == "__main__":
    unittest.main()
