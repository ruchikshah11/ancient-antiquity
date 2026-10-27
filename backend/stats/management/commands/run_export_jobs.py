from django.core.management.base import BaseCommand

from stats import exports


class Command(BaseCommand):
    help = "Run export jobs left pending or abandoned (e.g. after a server restart) and delete expired export files."

    def handle(self, *args, **options):
        ran = exports.run_pending()
        removed = exports.cleanup_expired()
        self.stdout.write(self.style.SUCCESS(f"Ran {ran} export job(s); removed {removed} expired file(s)."))
