"""PyInstaller 打包入口：把 src/mcvd 打成单文件 exe。

构建（在仓库根目录）：
    python -m PyInstaller --onefile --console --name mcvd --paths src packaging/entry.py
或直接运行：
    powershell -File packaging/build.ps1
"""

import sys

from mcvd.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
