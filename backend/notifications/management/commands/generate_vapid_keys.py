"""Print a fresh VAPID key pair for web push, ready to paste into .env.

Generate once per deployment; changing the keys invalidates every existing browser subscription.
"""
import base64

from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from py_vapid import Vapid


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Generate VAPID keys for web push notifications (prints .env lines)."

    def handle(self, *args, **opts):
        vapid = Vapid()
        vapid.generate_keys()
        private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        public = vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.stdout.write(f"VAPID_PUBLIC_KEY={_b64url(public)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={_b64url(private)}")
        self.stdout.write("VAPID_SUBJECT=mailto:support@ancientantiquity.in")
