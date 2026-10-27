"""Email guard: sample-data accounts never receive email, whatever backend is configured.

seed_demo_data creates realistic addresses (gmail.com, yahoo.co.in …) that may well belong to real people.
Those users are flagged User.is_sample; this backend removes them from to/cc/bcc and passes everything else to
settings.REAL_EMAIL_BACKEND (SMTP, file, console …).
"""
import logging
from email.utils import parseaddr

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


def sample_addresses(addresses):
    """The subset of `addresses` (plain or "Name <addr>") that belong to sample accounts, lower-cased."""
    from accounts.models import User

    plain = {parseaddr(a)[1].lower() for a in addresses if a}
    if not plain:
        return set()
    return {e.lower() for e in User.objects.filter(is_sample=True, email__in=plain).values_list("email", flat=True)}


class SampleSafeEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.real = get_connection(settings.REAL_EMAIL_BACKEND, fail_silently=fail_silently, **kwargs)

    def open(self):
        return self.real.open()

    def close(self):
        return self.real.close()

    def send_messages(self, email_messages):
        keep = []
        for message in email_messages or []:
            blocked = sample_addresses([*message.to, *message.cc, *message.bcc])
            if blocked:
                allowed = lambda addrs: [a for a in addrs if parseaddr(a)[1].lower() not in blocked]  # noqa: E731
                message.to, message.cc, message.bcc = allowed(message.to), allowed(message.cc), allowed(message.bcc)
                logger.info("Not emailing sample account(s): %s", ", ".join(sorted(blocked)))
            if message.to or message.cc or message.bcc:
                keep.append(message)
        return self.real.send_messages(keep) if keep else 0
