param(
    [string]$AdminUsername = "admin",
    [string]$AdminEmail = "admin@example.com",
    [string]$Python = "python",
    [switch]$Help
)

if ($Help) {
    Write-Host "Usage: powershell -ExecutionPolicy Bypass -File scripts\bootstrap_dev.ps1 -AdminUsername admin -AdminEmail admin@example.com"
    Write-Host "Creates venv, installs requirements.txt, copies .env.example when .env is missing, runs migrations, and creates an admin user."
    exit 0
}

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $Root

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Block
    )
    Write-Host ""
    Write-Host "==> $Title"
    & $Block
}

Invoke-Step "Create virtual environment" {
    if (-not (Test-Path "venv\Scripts\python.exe")) {
        & $Python -m venv venv
    } else {
        Write-Host "venv already exists, skipped."
    }
}

$VenvPython = Join-Path $Root "venv\Scripts\python.exe"

Invoke-Step "Install local development dependencies" {
    & $VenvPython -m pip install -r requirements.txt
}

Invoke-Step "Prepare .env" {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host ".env created from .env.example. Review it before commercial use."
    } else {
        Write-Host ".env already exists, skipped."
    }
}

Invoke-Step "Run database migrations" {
    & $VenvPython -m flask db upgrade
}

Invoke-Step "Create or repair admin user" {
    $argsList = @("scripts\create_admin.py", "--username", $AdminUsername)
    if ($AdminEmail) {
        $argsList += @("--email", $AdminEmail)
    }
    & $VenvPython @argsList
}

Write-Host ""
Write-Host "Bootstrap complete. Start the app with:"
Write-Host "venv\Scripts\python.exe run.py"
