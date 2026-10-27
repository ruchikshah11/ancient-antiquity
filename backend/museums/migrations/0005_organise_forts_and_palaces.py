"""Classify existing places and merge forts with the museum inside them where one ticket covers both."""
from django.db import migrations

# old name -> new name for fort + museum sold as a single ticket
MERGED_FORTS = {
    "Mehrangarh Fort Museum": "Mehrangarh Fort & Museum",
    "Junagarh Fort Museum": "Junagarh Fort & Museum",
    "Ramnagar Fort Museum": "Ramnagar Fort & Museum",
    "Archaeological Museum, Purana Qila": "Purana Qila & Museum",
}
# Taj Museum sits inside the Taj Mahal complex and is covered by the Taj Mahal ticket,
# which is added as its own place.
FOLDED_INTO_MONUMENT = ["Taj Museum"]


def forwards(apps, schema_editor):
    Museum = apps.get_model("museums", "Museum")
    Booking = apps.get_model("bookings", "Booking")

    Museum.objects.filter(category__name="Palace Museum").update(place_type="palace")
    for old, new in MERGED_FORTS.items():
        Museum.objects.filter(name=old).update(name=new, place_type="fort")
    for name in FOLDED_INTO_MONUMENT:
        for m in Museum.objects.filter(name=name):
            if Booking.objects.filter(museum=m).exists():
                Museum.objects.filter(pk=m.pk).update(is_active=False)
            else:
                m.delete()


def backwards(apps, schema_editor):
    Museum = apps.get_model("museums", "Museum")
    for old, new in MERGED_FORTS.items():
        Museum.objects.filter(name=new).update(name=old)
    Museum.objects.update(place_type="museum")


class Migration(migrations.Migration):
    dependencies = [
        ("museums", "0004_museum_place_type"),
        ("bookings", "0002_booking_channel_booking_sold_by_and_more"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
