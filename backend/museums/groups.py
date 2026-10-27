"""Is this kind of booking open right now? One answer for the API, the booking checks and the assistant.

Admin -> Settings has a site-wide switch per kind; each place also has its own Individual / Groups switches.
Ticket-counter sales by staff are never blocked: they are a decision made at the gate.
"""
from .models import SiteSettings

# kind -> (SiteSettings field, place field or None, default message)
KINDS = {
    "individual": ("individual_bookings_enabled", "allow_individual", "Online tickets are paused right now."),
    "instant": ("group_bookings_enabled", "allow_groups", "Group bookings are paused right now."),
    "request": ("group_requests_enabled", "allow_groups", "Requests for large groups are paused right now."),
    "school": ("school_trips_enabled", "allow_groups", "New school trip requests are paused right now."),
    "events": ("events_enabled", None, "Event tickets are paused right now."),
    "passes": ("passes_enabled", None, "Combo pass sales are paused right now."),
}
PLACE_MESSAGES = {
    "allow_individual": "{name} takes group bookings only.",
    "allow_groups": "{name} does not take group visits online.",
}


def block_reason(museum, kind):
    """None when `kind` is open (at `museum`, if given), otherwise the message to show visitors."""
    site_field, place_field, default_message = KINDS[kind]
    site = SiteSettings.load()
    if not getattr(site, site_field):
        return site.paused_message or default_message
    if museum is not None and place_field and not getattr(museum, place_field):
        return PLACE_MESSAGES[place_field].format(name=museum.name)
    return None


def is_open(museum, kind):
    return block_reason(museum, kind) is None


# Older names used across the code base.
def group_block_reason(museum, kind="instant"):
    return block_reason(museum, kind)


def groups_open(museum, kind="instant"):
    return is_open(museum, kind)
