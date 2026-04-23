param(
    [string]$Name = "VideoMergingTool"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
Set-Location $ProjectRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-build.txt

if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

& ".\.venv\Scripts\pyinstaller.exe" `
    --onefile `
    --clean `
    --name $Name `
    --collect-all typer `
    --collect-all click `
    --collect-all rich `
    --hidden-import videomerge.gui `
    --hidden-import tkinter `
    main.py

Write-Host ""
Write-Host "Build complete: $ProjectRoot\dist\$Name.exe"
Write-Host "Example:"
Write-Host "  .\dist\$Name.exe merge `"F:\Videos`" --mode fast"
