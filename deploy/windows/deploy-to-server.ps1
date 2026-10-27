<#
  Ancient Antiquity - deploy from this Windows PC to an Ubuntu server in one command (uses the built-in ssh/scp).

  First time (installs Docker, settings, HTTPS, backups on the server):
    .\deploy\windows\deploy-to-server.ps1 -Server ubuntu@203.0.113.10 -Domain tickets.example.in -Email you@example.in
  Every later update (backup, rebuild, restart, health check):
    .\deploy\windows\deploy-to-server.ps1 -Server ubuntu@203.0.113.10
  Only build the package (to copy it some other way):
    .\deploy\windows\deploy-to-server.ps1 -PackageOnly

  Options: -Path /srv/ancient-antiquity (install folder), -Key C:\keys\server.pem (ssh key), -NoHttps (IP-only trial).
  Never uploaded: .env files (secrets stay on each machine), the local database and backups, logs, node_modules,
  .venv, and docs\LOGIN_DETAILS.md / docs\sample-users.csv (demo passwords).
#>
param(
    [string]$Server,
    [string]$Domain,
    [string]$Email,
    [string]$Path = '/srv/ancient-antiquity',
    [string]$Key,
    [switch]$NoHttps,
    [switch]$PackageOnly
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

if (-not $PackageOnly -and -not $Server) { throw 'Give -Server user@host (or -PackageOnly). See the top of this script.' }

Step 'Package the code'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $env:TEMP "ancient-antiquity-$stamp.tar.gz"
$exclude = @(
    '.git', 'node_modules', '.venv', 'venv', '__pycache__', '*.pyc', 'dist', '.vite', 'test-results', 'playwright-report',
    '.env', 'db.sqlite3*', '*.sqlite3', 'backend/backups', 'backend/logs', 'backend/sent_emails', 'backend/exports',
    'backend/media', 'docs/LOGIN_DETAILS.md', 'docs/sample-users.csv', '.vscode', '.idea'
) | ForEach-Object { "--exclude=$_" }
# Windows tar (bsdtar) matches each pattern against every path component, e.g. '.env' but not '.env.example'.
tar.exe -czf $out @exclude -C $root .
if ($LASTEXITCODE -ne 0) { throw 'packaging failed' }
Write-Host ("{0} ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB))
if ($PackageOnly) { return }

$sshArgs = @('-o', 'ServerAliveInterval=30')
if ($Key) { $sshArgs += @('-i', $Key) }

Step "Upload to $Server"
scp @sshArgs $out "${Server}:/tmp/ancient-antiquity.tar.gz"
if ($LASTEXITCODE -ne 0) { throw 'upload failed (check -Server, -Key and that ssh works: ssh user@host)' }

Step 'Install / update on the server'
$unpack = "sudo mkdir -p $Path && sudo tar -xzf /tmp/ancient-antiquity.tar.gz -C $Path && rm -f /tmp/ancient-antiquity.tar.gz " +
          "&& cd $Path && sudo sed -i 's/\r$//' deploy/*.sh && sudo chmod +x deploy/*.sh"
if ($Domain) {
    $https = if ($NoHttps) { '--no-https' } elseif ($Email) { "--email $Email" } else { throw 'Give -Email for HTTPS (or -NoHttps).' }
    $remote = "$unpack && sudo ./deploy/install.sh --domain $Domain $https"
} else {
    $remote = "$unpack && if [ -f backend/.env ]; then sudo ./deploy/update.sh --no-pull; " +
              "else echo 'First deployment: run again with -Domain and -Email'; exit 1; fi"
}
ssh @sshArgs -t $Server $remote
if ($LASTEXITCODE -ne 0) { throw "server step failed (exit $LASTEXITCODE) - output above" }
Remove-Item $out
Write-Host "`nDeployed." -ForegroundColor Green
