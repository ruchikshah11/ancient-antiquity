"""Background job runner for servers: runs the periodic management commands on a fixed timetable (India time).

Used by the "jobs" service in docker-compose.yml and by deploy/systemd/ancient-antiquity-jobs.service, so a
server needs no cron entries for the app itself. (On a Windows PC, Task Scheduler runs the same commands through
scripts/run_hidden.py instead - see deploy/windows/register-tasks.ps1.)

    python scripts/run_jobs.py            # run forever
    python scripts/run_jobs.py --list     # show the timetable
    python scripts/run_jobs.py --once recovery   # run one job now and exit

Every command is safe to re-run (each tracks what it already sent/built), so a restart never double-sends.
"""
import datetime
import os
import sys
import time
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ancient_antiquity.settings")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import close_old_connections  # noqa: E402
from django.utils import timezone  # noqa: E402

# name -> (when it is due, commands). `due(now)` is checked once a minute with India time.
JOBS = {
    "recovery": (lambda t: t.minute % 15 == 0, [["send_recovery_emails"]]),
    "reminders-soon": (lambda t: t.minute == 5, [["send_visit_reminders", "--hours-before", "2"]]),
    "reminders-tomorrow": (lambda t: (t.hour, t.minute) == (18, 0), [["send_visit_reminders"]]),
    "exports": (lambda t: t.minute == 40, [["run_export_jobs"]]),
    "stats": (lambda t: (t.hour, t.minute) == (2, 30), [["rebuild_stats", "--days", "2"]]),
    "sessions": (lambda t: (t.weekday(), t.hour, t.minute) == (6, 4, 0), [["clearsessions"]]),
}
TIMETABLE = {
    "recovery": "every 15 minutes",
    "reminders-soon": "hourly at :05 (slots starting within 2 hours)",
    "reminders-tomorrow": "daily 18:00 (tomorrow's visits)",
    "exports": "hourly at :40 (pending exports, expired files)",
    "stats": "daily 02:30 (last 2 days of statistics)",
    "sessions": "Sundays 04:00 (expired logins)",
}


def log(msg):
    print(f"[{timezone.localtime():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def run(name):
    for command in JOBS[name][1]:
        log(f"{name}: {' '.join(command)}")
        try:
            call_command(*command)
        except Exception:  # one failing job must not stop the others
            log(f"{name} FAILED:\n{traceback.format_exc()}")
        finally:
            close_old_connections()


def main():
    args = sys.argv[1:]
    if "--list" in args:
        for name, text in TIMETABLE.items():
            print(f"  {name:20} {text}")
        return
    if "--once" in args:
        names = args[args.index("--once") + 1:] or list(JOBS)
        for name in names:
            run(name)
        return

    log("job runner started (India time); timetable: " + "; ".join(f"{n} {t}" for n, t in TIMETABLE.items()))
    last_minute = None
    while True:
        now = timezone.localtime().replace(second=0, microsecond=0)
        if now != last_minute:
            last_minute = now
            for name, (due, _commands) in JOBS.items():
                if due(now):
                    run(name)
        # wake shortly after the next minute starts
        time.sleep(max(1.0, 61 - datetime.datetime.now().second))


if __name__ == "__main__":
    main()
