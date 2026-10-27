<#
  Ancient Antiquity - set up a Windows PC for development in one go (safe to run again; finished steps are skipped).

    .\deploy\windows\setup-dev.ps1               # backend venv + packages, .env, database, places, frontend, tasks
    .\deploy\windows\setup-dev.ps1 -NoTasks      # without the Task Scheduler jobs

  Needs Python 3.12 and Node.js 18+ installed. Afterwards start both servers with .\start.ps1
#>
param([switch]$NoTasks)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

Step 'Tools'
$py, $pyArgs = if (Get-Command py -ErrorAction SilentlyContinue) { 'py', @('-3.12') } else { 'python', @() }
& $py @pyArgs --version; Check 'Python 3.12'
node --version; Check 'Node.js'

Step 'Backend packages'
$venvPy = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { & $py @pyArgs -m venv (Join-Path $backend '.venv'); Check 'venv' }
& $venvPy -m pip install --quiet --disable-pip-version-check -r (Join-Path $backend 'requirements.txt'); Check 'pip install'

Step 'Settings (backend\.env)'
$envFile = Join-Path $backend '.env'
if (Test-Path $envFile) {
    Write-Host 'keeping the existing backend\.env'
} else {
    # Local development: SQLite, demo payment gateway, emails written to backend\sent_emails.
    (Get-Content (Join-Path $backend '.env.example')) -replace '^DATABASE_URL=.*', 'DATABASE_URL=sqlite:///db.sqlite3' |
        Set-Content $envFile -Encoding utf8
    Write-Host 'created backend\.env (SQLite). Add your own keys to it later.'
}

Step 'Database'
$env:PYTHONUTF8 = '1'
Push-Location $backend
try {
    & $venvPy manage.py migrate --noinput; Check 'migrate'
    $places = (& $venvPy manage.py shell -c "from museums.models import Museum; print(Museum.objects.count())" | Select-Object -Last 1)
    if ([int]$places -eq 0) {
        Write-Host 'Empty database: loading places, photos and sample data (a few minutes)...'
        & $venvPy manage.py seed_india --demo-users; Check 'seed_india'
        foreach ($cmd in @('enrich_museums', 'import_listed_museums museums/data/listed_museums.json', 'fetch_more_photos',
                           'seed_holidays', 'seed_virtual_tours', 'seed_addons', 'seed_memberships', 'seed_passes',
                           'seed_events', 'rebuild_stats')) {
            & $venvPy manage.py @($cmd -split ' '); Check $cmd
        }
        Write-Host 'Demo logins: docs\LOGIN_DETAILS.md. More sample users/bookings: manage.py seed_demo_data --append'
    } else {
        Write-Host "database already has $places places - nothing loaded"
    }
} finally { Pop-Location }

Step 'Frontend packages'
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Push-Location $frontend
    try { npm ci --no-audit --no-fund; Check 'npm ci' } finally { Pop-Location }
} else { Write-Host 'node_modules present' }

if (-not $NoTasks) {
    Step 'Background jobs (Task Scheduler, hidden)'
    & (Join-Path $PSScriptRoot 'register-tasks.ps1')
}

Write-Host "`nReady. Start the site with: .\start.ps1  (API http://127.0.0.1:8000, site http://127.0.0.1:5173)" -ForegroundColor Green
