param(
    [string]$Name = "VideoMergingTool"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # 加快下载速度

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
Set-Location $ProjectRoot
$IconPath = Join-Path $ProjectRoot "assets\icons\VideoMergingTool.ico"
$VendorFfmpegDir = Join-Path $ProjectRoot "build\vendor\ffmpeg"
$BuildTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Building $Name on Windows" -ForegroundColor Cyan
Write-Host "Start Time: $BuildTimestamp" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 创建虚拟环境（如果不存在）
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment"
    }
}

# 检查并升�� pip（缓存检查）
Write-Host "Checking Python environment..." -ForegroundColor Yellow
$PythonExe = ".\.venv\Scripts\python.exe"
$PipExe = ".\.venv\Scripts\pip.exe"

# 加速 pip 安装（使用本地缓存）
& $PipExe install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "Warning: pip upgrade had issues, continuing anyway..." -ForegroundColor Yellow
}

Write-Host "Installing build dependencies..." -ForegroundColor Yellow
& $PipExe install -r requirements-build.txt --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install build dependencies"
}

# 获取版本号
Write-Host "Reading version information..." -ForegroundColor Yellow
$Version = (& $PythonExe -c "from videomerge import __version__; print(__version__)").Trim()
if (-not $Version) {
    throw "Failed to read version"
}
Write-Host "Version: $Version" -ForegroundColor Green
$VersionFile = Join-Path $ProjectRoot "build\version_info.txt"

# 签名函数
function Invoke-WindowsSigning {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Host "Error: File not found for signing: $Path" -ForegroundColor Red
        return $false
    }

    if (-not $env:WINDOWS_CERTIFICATE_BASE64 -or -not $env:WINDOWS_CERTIFICATE_PASSWORD) {
        Write-Host "Code signing skipped: certificate secrets not configured" -ForegroundColor Yellow
        return $true
    }

    $SignTool = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if (-not $SignTool) {
        Write-Host "Code signing skipped: signtool.exe not found" -ForegroundColor Yellow
        return $true
    }

    try {
        Write-Host "Signing: $(Split-Path -Leaf $Path)" -ForegroundColor Yellow
        $CertPath = Join-Path ([System.IO.Path]::GetTempPath()) "videomerge_$(Get-Random).pfx"
        
        [System.IO.File]::WriteAllBytes($CertPath, [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE_BASE64))
        
        & $SignTool.Source sign /fd SHA256 /td SHA256 /tr "http://timestamp.digicert.com" /f $CertPath /p $env:WINDOWS_CERTIFICATE_PASSWORD $Path
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Warning: Signing may have failed, continuing anyway..." -ForegroundColor Yellow
            return $true
        }
        
        Remove-Item -Force $CertPath -ErrorAction SilentlyContinue
        Write-Host "✓ Signed successfully" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "Warning: Signing failed: $_" -ForegroundColor Yellow
        return $true  # 不中断构建
    }
}

# 清理之前的构建
if (Test-Path "build") {
    Write-Host "Cleaning previous build artifacts..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "build"
}

# 准备 FFmpeg
Write-Host "Preparing FFmpeg binaries (this may take a minute)..." -ForegroundColor Yellow
& $PythonExe "scripts\prepare_ffmpeg.py" --output $VendorFfmpegDir --force
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare FFmpeg"
}

# 生成 Windows 版本信息
Write-Host "Generating version information..." -ForegroundColor Yellow
& $PythonExe "scripts\write_windows_version.py" $VersionFile
if ($LASTEXITCODE -ne 0) {
    throw "Failed to write version file"
}

# 构建可执行文件
Write-Host "Running PyInstaller (this may take 2-3 minutes)..." -ForegroundColor Yellow
$PyInstallerArgs = @(
    "--onefile",
    "--windowed",
    "--clean",
    "--noconfirm",
    "--name", $Name,
    "--icon", $IconPath,
    "--version-file", $VersionFile,
    "--collect-all", "typer",
    "--collect-all", "click",
    "--collect-all", "rich",
    "--collect-all", "webview",
    "--collect-all", "certifi",
    "--hidden-import", "videomerge.gui",
    "--hidden-import", "tkinter",
    "--distpath", "dist",
    "--buildpath", "build/pyinstaller",
    "--specpath", "build",
    "main.py"
)

$PyInstallerExe = ".\.venv\Scripts\pyinstaller.exe"
& $PyInstallerExe @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

$ExePath = Join-Path $ProjectRoot "dist\$Name.exe"
if (-not (Test-Path $ExePath)) {
    throw "Executable not found at $ExePath"
}

Write-Host "✓ Executable created: $Name.exe" -ForegroundColor Green

# 签名主程序
Invoke-WindowsSigning -Path $ExePath

# 复制 FFmpeg
Write-Host "Preparing FFmpeg files..." -ForegroundColor Yellow
$FfmpegOutDir = Join-Path $ProjectRoot "dist\ffmpeg"
New-Item -ItemType Directory -Force -Path $FfmpegOutDir | Out-Null

$FfmpegSrc = Join-Path $VendorFfmpegDir "ffmpeg.exe"
$FfprobeSrc = Join-Path $VendorFfmpegDir "ffprobe.exe"

if (-not (Test-Path $FfmpegSrc) -or -not (Test-Path $FfprobeSrc)) {
    throw "FFmpeg binaries not found in $VendorFfmpegDir"
}

Copy-Item $FfmpegSrc (Join-Path $FfmpegOutDir "ffmpeg.exe") -Force
Copy-Item $FfprobeSrc (Join-Path $FfmpegOutDir "ffprobe.exe") -Force
Write-Host "✓ FFmpeg files prepared" -ForegroundColor Green

# 构建安装程序
$Inno = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($Inno) {
    Write-Host "Building Inno Setup installer..." -ForegroundColor Yellow
    $InstallerDir = Join-Path $ProjectRoot "dist\installer"
    New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null
    $IssPath = Join-Path $InstallerDir "$Name.iss"
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
TimeStampsInUTC=yes

[Files]
Source: "$ExePath"; DestDir: "{app}"; Flags: ignoreversion
Source: "$ProjectRoot\dist\ffmpeg\*"; DestDir: "{app}\ffmpeg"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\$Name"; Filename: "{app}\$Name.exe"
Name: "{userdesktop}\$Name"; Filename: "{app}\$Name.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"
"@ | Set-Content -Path $IssPath -Encoding UTF8

    & $Inno.Source $IssPath
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed"
    }

    $InstallerPath = Join-Path $InstallerDir "$Name-Setup.exe"
    if (-not (Test-Path $InstallerPath)) {
        throw "Installer not found at $InstallerPath"
    }

    # 签名安装程序
    Invoke-WindowsSigning -Path $InstallerPath
    
    Write-Host "✓ Installer created: $InstallerDir\$Name-Setup.exe" -ForegroundColor Green
} else {
    Write-Host "⚠ Inno Setup not found; installer generation skipped" -ForegroundColor Yellow
    Write-Host "  Install Inno Setup and rerun to produce installer" -ForegroundColor Yellow
}

$EndTimestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "✓ Build Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Build artifacts: $ProjectRoot\dist"
Write-Host "End Time: $EndTimestamp" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
