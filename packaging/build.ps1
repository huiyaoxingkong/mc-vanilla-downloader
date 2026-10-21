# 构建单文件 exe（GUI + CLI 两个）
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

function Build-Exe([string]$Name, [string]$WindowMode) {
    $args = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        $WindowMode,
        "--name", $Name,
        "--distpath", "dist",
        "--workpath", "build/pyinstaller-$Name",
        "--specpath", "build",
        "--paths", "src",
        "--collect-all", "customtkinter",
        "--collect-submodules", "mcvd",
        "--hidden-import", "mcvd.gui",
        "packaging/entry.py"
    )
    if (-not $KeepBuild) { $args += "--clean" }
    & $PythonExe @args
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建 $Name 失败" }
}

Write-Host "`n[1/2] 构建图形界面版 mcvd.exe（无控制台窗口）"
Build-Exe "mcvd" "--windowed"

Write-Host "`n[2/2] 构建命令行版 mcvd-cli.exe（保留控制台）"
Build-Exe "mcvd-cli" "--console"

Write-Host ""
Write-Host "构建完成："
Get-ChildItem "dist/*.exe" | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 2) } }, LastWriteTime | Format-Table -AutoSize
