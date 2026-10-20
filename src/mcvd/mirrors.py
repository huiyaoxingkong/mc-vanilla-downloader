"""下载源（镜像）定义与 URL 重写。

Mojang 官方下载地址分散在若干个域名上，国内镜像（目前事实标准是 BMCLAPI）
通过"同路径 + 少量前缀映射"的方式镜像这些文件。本模块只做纯函数式的 URL
重写，不做任何网络请求，便于单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

# 官方版本清单地址（v2，含 sha1 与发布时间）
OFFICIAL_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"

# 官方域名 -> 镜像上的路径前缀（前缀为空表示路径保持一致）
OFFICIAL_HOST_PREFIX = {
    "launchermeta.mojang.com": "",
    "piston-meta.mojang.com": "",
    "piston-data.mojang.com": "",
    "libraries.minecraft.net": "/maven",
    "resources.download.minecraft.net": "/assets",
}

# 旧版（1.6 之前）版本 JSON 里 client.jar 可能直接写在 launcher.mojang.com
LEGACY_HOST_PREFIX = {
    "launcher.mojang.com": "",
}


@dataclass(frozen=True)
class Mirror:
    """一个下载源。

    base 为 None 表示直接使用官方原始地址（不做重写）。
    """

    name: str
    base: str | None
    description: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def rewrite(self, official_url: str) -> str:
        """把官方 URL 重写成该镜像上的等价 URL；无法识别时原样返回。"""
        if self.base is None:
            return official_url
        parts = urlsplit(official_url)
        prefix = OFFICIAL_HOST_PREFIX.get(parts.netloc)
        if prefix is None:
            prefix = LEGACY_HOST_PREFIX.get(parts.netloc, "")
            if parts.netloc not in LEGACY_HOST_PREFIX:
                return official_url
        return urlunsplit((parts.scheme, urlsplit(self.base).netloc, prefix + parts.path, parts.query, ""))

    def manifest_url(self) -> str:
        return self.rewrite(OFFICIAL_MANIFEST_URL)

    # 用于健康检查的多个候选地址
    def probe_urls(self, version_json_url: str, client_jar_url: str) -> list[str]:
        return [self.rewrite(version_json_url), self.rewrite(client_jar_url)]


MIRROR_OFFICIAL = Mirror(
    name="official",
    base=None,
    description="Mojang 官方源（跨境，网络波动时可能较慢）",
    aliases=("mojang", "官方"),
)

MIRROR_BMCLAPI = Mirror(
    name="bmclapi",
    base="https://bmclapi2.bangbang93.com",
    description="BMCLAPI 国内镜像（bangbang93 维护，社区公益服务）",
    aliases=("bmcl", "bangbang93", "国内"),
)

ALL_MIRRORS = [MIRROR_OFFICIAL, MIRROR_BMCLAPI]


def get_mirror(name: str) -> Mirror:
    lowered = name.strip().lower()
    for mirror in ALL_MIRRORS:
        if lowered == mirror.name or lowered in mirror.aliases:
            return mirror
    raise KeyError(f"未知的下载源：{name}（可选：auto / official / bmclapi）")


def make_custom_mirror(base_url: str) -> Mirror:
    """支持用户自建镜像：按 BMCLAPI 的路径约定重写。"""
    return Mirror(name="custom", base=base_url.rstrip("/"), description=f"自定义镜像 {base_url}")
