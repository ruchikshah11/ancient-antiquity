"""Bulk add museums from a CSV file (open/save it from Excel as "CSV UTF-8").

    python manage.py import_museums my_museums.csv
    python manage.py import_museums my_museums.csv --update   # also overwrite existing rows

See museums/importer.py for the column list.
"""
from django.core.management.base import BaseCommand, CommandError

from museums.importer import import_museums


class Command(BaseCommand):
    help = "Import museums from a CSV file"

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--update", action="store_true", help="Update museums that already exist")

    def handle(self, csv_path, update=False, **opts):
        try:
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                result = import_museums(f, update=update)
        except FileNotFoundError:
            raise CommandError(f"File not found: {csv_path}")
        for err in result["errors"]:
            self.stderr.write(f"  row {err['row']} {err.get('name', '')}: {err['error']}")
        self.stdout.write(self.style.SUCCESS(
            f"created {result['created']}, updated {result['updated']}, "
            f"skipped {result['skipped']} (already exist), errors {len(result['errors'])}"
        ))
