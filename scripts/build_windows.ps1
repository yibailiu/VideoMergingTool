param(
    [string]$Name = "VideoMergingTool"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
Set-Location $ProjectRoot
$IconPath = Join-Path $ProjectRoot "assets\icons\VideoMergingTool.ico"
$VendorFfmpegDir = Join-Path $ProjectRoot "build\vendor\ffmpeg"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-build.txt
$Version = (& ".\.venv\Scripts\python.exe" -c "from videomerge import __version__; print(__version__)").Trim()
$VersionFile = Join-Path $ProjectRoot "build\version_info.txt"

if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

& ".\.venv\Scripts\python.exe" "scripts\prepare_ffmpeg.py" --output $VendorFfmpegDir --force
& ".\.venv\Scripts\python.exe" "scripts\write_windows_version.py" $VersionFile

& ".\.venv\Scripts\pyinstaller.exe" `
    --onefile `
    --windowed `
    --clean `
    --noconfirm `
    --name $Name `
    --icon $IconPath `
    --version-file $VersionFile `
    --collect-all typer `
    --collect-all click `
    --collect-all rich `
    --collect-all webview `
    --collect-all certifi `
    --hidden-import videomerge.gui `
    --hidden-import tkinter `
    main.py

Write-Host ""
Write-Host "Build complete: $ProjectRoot\dist\$Name.exe"
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "dist\ffmpeg") | Out-Null
Copy-Item (Join-Path $VendorFfmpegDir "ffmpeg.exe") (Join-Path $ProjectRoot "dist\ffmpeg\ffmpeg.exe") -Force
Copy-Item (Join-Path $VendorFfmpegDir "ffprobe.exe") (Join-Path $ProjectRoot "dist\ffmpeg\ffprobe.exe") -Force

$Inno = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($Inno) {
    $InstallerDir = Join-Path $ProjectRoot "dist\installer"
    New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null
    $IssPath = Join-Path $InstallerDir "$Name.iss"
    $ExePath = Join-Path $ProjectRoot "dist\$Name.exe"
    $AppId = "{{A5D42E7E-49A6-4CFB-9671-51B4B8B82E73}"
    @"
[Setup]
AppId=$AppId
AppName=$Name
AppVersion=$Version
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\$Name
DefaultGroupName=$Name
OutputDir=$InstallerDir
OutputBaseFilename=$Name-Setup
SetupIconFile=$IconPath
Compression=lzma
SolidCompression=yes

[Files]
Source: "$ExePath"; DestDir: "{app}"; Flags: ignoreversion
Source: "$ProjectRoot\dist\ffmpeg\*"; DestDir: "{app}\ffmpeg"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\$Name"; Filename: "{app}\$Name.exe"
Name: "{commondesktop}\$Name"; Filename: "{app}\$Name.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"
"@ | Set-Content -Path $IssPath -Encoding UTF8
    & $Inno.Source $IssPath
    Write-Host "Installer complete: $InstallerDir\$Name-Setup.exe"
} else {
    Write-Host "Inno Setup was not found; installer generation skipped."
    Write-Host "Install Inno Setup and rerun this script to produce dist\installer\$Name-Setup.exe."
}
