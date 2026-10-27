"""ASI admits children under 15 free: rename the child/adult age bands at ASI-run places."""
from django.db import migrations

ASI = "Archaeological Survey of India"


def forwards(apps, schema_editor):
    TicketType = apps.get_model("museums", "TicketType")
    asi = TicketType.objects.filter(museum__managed_by=ASI)
    asi.filter(name="Child (below 12)").update(
        name="Child (below 15)", description="Free entry under 15 (ASI rule), accompanied by an adult"
    )
    asi.filter(name="Indian Citizen (Adult)", description="Indian nationals aged 12+").update(
        description="Indian nationals aged 15+"
    )


def backwards(apps, schema_editor):
    TicketType = apps.get_model("museums", "TicketType")
    asi = TicketType.objects.filter(museum__managed_by=ASI)
    asi.filter(name="Child (below 15)").update(name="Child (below 12)", description="Accompanied by an adult")
    asi.filter(name="Indian Citizen (Adult)", description="Indian nationals aged 15+").update(
        description="Indian nationals aged 12+"
    )


class Migration(migrations.Migration):
    dependencies = [("museums", "0005_organise_forts_and_palaces")]

    operations = [migrations.RunPython(forwards, backwards)]
