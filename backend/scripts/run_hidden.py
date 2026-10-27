"""Run Django management commands in the background without a console window (for Windows Task Scheduler).

Use with pythonw.exe so nothing pops up on screen:
    pythonw.exe scripts\\run_hidden.py <log name> <command> [args] [+ <command> [args] ...]
e.g.
    pythonw.exe scripts\\run_hidden.py recovery_emails send_recovery_emails
    pythonw.exe scripts\\run_hidden.py rebuild_stats rebuild_stats --days 2 + run_export_jobs

Output and errors are appended to backend/logs/<log name>.log.
"""
import datetime
import os
import sys
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ancient_antiquity.settings")


def main():
    if len(sys.argv) < 3:
        return
    log_name, args = sys.argv[1], sys.argv[2:]
    (BACKEND / "logs").mkdir(exist_ok=True)
    with open(BACKEND / "logs" / f"{log_name}.log", "a", encoding="utf-8") as log:
        log.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}]\n")
        try:
            import django
            from django.core.management import call_command

            django.setup()
            command = []
            for part in args + ["+"]:
                if part == "+":
                    if command:
                        call_command(*command, stdout=log, stderr=log)
                    command = []
                else:
                    command.append(part)
        except Exception:  # keep the scheduler quiet; the log has the details
            log.write(traceback.format_exc())


if __name__ == "__main__":
    main()
