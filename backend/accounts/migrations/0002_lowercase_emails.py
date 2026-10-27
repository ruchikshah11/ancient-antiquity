"""Store emails in lowercase so logins and password resets are case-insensitive."""
from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    seen = set(User.objects.values_list("email", flat=True))
    for user in User.objects.all():
        lower = user.email.strip().lower()
        if lower == user.email:
            continue
        if lower in seen:
            # Two accounts differing only by case: leave this one as is (an admin should merge them).
            continue
        seen.add(lower)
        user.email = lower
        user.save(update_fields=["email"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
