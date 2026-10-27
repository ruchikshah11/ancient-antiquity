import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0006_booking_promo_code_booking_promo_discount_and_more"),
        ("museums", "0010_gate"),
    ]

    operations = [
        migrations.AddField(
            model_name="gatescan",
            name="gate",
            field=models.ForeignKey(
                blank=True, help_text="Gate that admitted this scan (empty = not recorded)", null=True,
                on_delete=django.db.models.deletion.SET_NULL, related_name="scans", to="museums.gate",
            ),
        ),
    ]
