<#
  Ancient Antiquity - register the background jobs in Windows Task Scheduler (folder \AncientAntiquity).
  They run with pythonw.exe (no console window ever pops up); output goes to backend\logs\<name>.log.

    .\deploy\windows\register-tasks.ps1            # create / update the tasks
    .\deploy\windows\register-tasks.ps1 -Remove    # delete them

  On a server the same jobs run in the "jobs" container instead (backend\scripts\run_jobs.py).
#>
param([switch]$Remove)

$backend = (Resolve-Path "$PSScriptRoot\..\..\backend").Path
$pythonw = Join-Path $backend '.venv\Scripts\pythonw.exe'
$runner = Join-Path $backend 'scripts\run_hidden.py'

# name -> schtasks schedule arguments, log name, command(s)
$tasks = @(
    @{ Name = 'SendRecoveryEmails'; Schedule = @('/SC', 'MINUTE', '/MO', '15'); Args = 'recovery_emails send_recovery_emails' },
    @{ Name = 'RebuildStats'; Schedule = @('/SC', 'DAILY', '/ST', '02:30'); Args = 'rebuild_stats rebuild_stats --days 2 + run_export_jobs' }
)

foreach ($t in $tasks) {
    $name = "AncientAntiquity\$($t.Name)"
    if ($Remove) {
        schtasks /Delete /F /TN $name 2>$null | Out-Null
        Write-Host "removed $name"
        continue
    }
    if (-not (Test-Path $pythonw)) { throw "Missing $pythonw - run deploy\windows\setup-dev.ps1 first." }
    $run = "`"$pythonw`" `"$runner`" $($t.Args)"
    schtasks /Create /F /TN $name /TR $run @($t.Schedule) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "could not create $name" }
    Write-Host "registered $name ($($t.Schedule -join ' ')) - hidden, log: backend\logs\$(($t.Args -split ' ')[0]).log"
}
