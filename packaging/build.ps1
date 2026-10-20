# 构建单文件 exe
# 用法：
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1
#   powershell -ExecutionPolicy Bypass -File packaging/build.ps1 -PythonExe "C:\Python312\python.exe"
param(
    [string]$PythonExe = "python",
    [switch]$KeepBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "使用 Python：$PythonExe"
& $PythonExe -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "未安装 PyInstaller，正在安装……"
    & $PythonExe -m pip install pyinstaller
}

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--console",
    "--name", "mcvd",
    "--distpath", "dist",
    "--workpath", "build/pyinstaller",
    "--specpath", "build",
    "--paths", "src",
    "packaging/entry.py"
)
if (-not $KeepBuild) { $args += "--clean" }

& $PythonExe @args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

Write-Host ""
Write-Host "构建完成：$root\dist\mcvd.exe"
Get-Item "dist/mcvd.exe" | Select-Object FullName, Length, LastWriteTime | Format-List
