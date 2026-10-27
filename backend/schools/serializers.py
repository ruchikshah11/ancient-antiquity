from decimal import Decimal

from rest_framework import serializers

from bookings.serializers import BookingSerializer
from museums.models import Museum, State, TimeSlot

from . import services
from .models import School, SchoolTrip

PHONE_RE = r"^\+?[0-9]{10,13}$"
PHONE_ERR = {"invalid": "Enter a valid phone number."}

# Fields a verified school may still change itself (the rest needs re-verification by an admin).
CONTACT_FIELDS = ("contact_name", "contact_phone", "contact_email", "principal_name", "phone")


class SchoolSerializer(serializers.ModelSerializer):
    state = serializers.PrimaryKeyRelatedField(queryset=State.objects.all())
    state_name = serializers.CharField(source="state.name", read_only=True)
    board_label = serializers.CharField(source="get_board_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    owner_email = serializers.CharField(source="owner.email", read_only=True)
    verified_by_email = serializers.CharField(source="verified_by.email", read_only=True, default=None)
    udise_code = serializers.RegexField(r"^\d{11}$", required=False, allow_blank=True,
                                        error_messages={"invalid": "A UDISE code has exactly 11 digits."})
    phone = serializers.RegexField(PHONE_RE, error_messages=PHONE_ERR)
    contact_phone = serializers.RegexField(PHONE_RE, error_messages=PHONE_ERR)
    trip_count = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = (
            "id", "name", "board", "board_label", "udise_code", "address", "city", "state", "state_name",
            "principal_name", "phone", "contact_name", "contact_phone", "contact_email", "status", "status_label",
            "rejection_reason", "verified_by_email", "verified_at", "owner_email", "trip_count", "created_at",
            "updated_at",
        )
        read_only_fields = ("status", "rejection_reason", "verified_at", "created_at", "updated_at")

    def get_trip_count(self, obj):
        n = getattr(obj, "n_trips", None)
        return obj.trips.count() if n is None else n

    def validate(self, attrs):
        school = self.instance
        if school is not None and school.is_verified:
            locked = [f for f in attrs if f not in CONTACT_FIELDS and attrs[f] != getattr(school, f)]
            if locked:
                raise serializers.ValidationError(
                    "A verified school can only change its contact details. Write to support to change the rest."
                )
        return attrs


class SchoolDecisionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class EstimateLineSerializer(serializers.Serializer):
    kind = serializers.CharField()
    name = serializers.CharField()
    quantity = serializers.IntegerField()
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


def estimate_data(est):
    tickets = est["tickets"]

    def tk(t):
        return t and {"id": t.id, "name": t.name, "price": f"{t.price:.2f}"}

    return {
        "lines": EstimateLineSerializer(est["lines"], many=True).data,
        "students": est["students"],
        "young_students": est["young_students"],
        "teachers": est["teachers"],
        "helpers": est["helpers"],
        "free_teachers": est["free_teachers"],
        "teachers_needed": services.teachers_needed(est["students"]),
        "people": est["people"],
        "subtotal": f"{est['subtotal']:.2f}",
        "discount_percent": est["discount_percent"],
        "discount": f"{est['discount']:.2f}",
        "total": f"{est['total']:.2f}",
        "student_ticket": tk(tickets["student"]),
        "child_ticket": tk(tickets["child"]),
        "adult_ticket": tk(tickets["adult"]),
    }


class ClassSizeMixin(serializers.Serializer):
    students = serializers.IntegerField(min_value=services.MIN_STUDENTS, max_value=services.MAX_STUDENTS, error_messages={
        "min_value": f"A class trip needs at least {services.MIN_STUDENTS} students.",
        "max_value": f"Up to {services.MAX_STUDENTS} students per trip. Split larger groups into several trips.",
    })
    young_students = serializers.IntegerField(min_value=0, default=0)
    teachers = serializers.IntegerField(min_value=1, max_value=100)
    helpers = serializers.IntegerField(min_value=0, max_value=100, default=0)

    def check_class(self, attrs):
        students, teachers = attrs["students"], attrs["teachers"]
        if attrs.get("young_students", 0) > students:
            raise serializers.ValidationError({"young_students": "Can't be more than the number of students."})
        needed = services.teachers_needed(students)
        if teachers < needed:
            raise serializers.ValidationError({"teachers": (
                f"At least 1 teacher per {services.STUDENTS_PER_FREE_TEACHER} students is required: "
                f"{needed} teacher(s) for {students} students."
            )})


class EstimateSerializer(ClassSizeMixin):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.filter(is_active=True))
    date = serializers.DateField(required=False)
    teachers = serializers.IntegerField(min_value=0, max_value=100, default=0)
    students = serializers.IntegerField(min_value=1, max_value=services.MAX_STUDENTS)


class SchoolTripSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    school_name = serializers.CharField(source="school.name", read_only=True)
    school_city = serializers.CharField(source="school.city", read_only=True)
    school_board = serializers.CharField(source="school.get_board_display", read_only=True)
    contact_name = serializers.CharField(source="school.contact_name", read_only=True)
    contact_email = serializers.CharField(source="school.contact_email", read_only=True)
    contact_phone = serializers.CharField(source="school.contact_phone", read_only=True)
    museum_name = serializers.CharField(source="museum.name", read_only=True)
    museum_slug = serializers.CharField(source="museum.slug", read_only=True)
    city_name = serializers.CharField(source="museum.city.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    slot_preference_label = serializers.CharField(source="get_slot_preference_display", read_only=True)
    guide_language_label = serializers.CharField(source="get_guide_language_display", read_only=True)
    decided_by_email = serializers.CharField(source="decided_by.email", read_only=True, default=None)
    booking = BookingSerializer(read_only=True)
    free_teachers = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_pay = serializers.SerializerMethodField()

    class Meta:
        model = SchoolTrip
        fields = (
            "id", "reference", "school", "school_name", "school_city", "school_board", "contact_name",
            "contact_email", "contact_phone", "museum_name", "museum_slug", "city_name", "preferred_date",
            "alternative_date", "slot_preference", "slot_preference_label", "grades", "students", "young_students",
            "teachers", "helpers", "free_teachers", "accessibility_needs", "guide_language", "guide_language_label",
            "notes", "status", "status_label", "estimated_amount", "quoted_amount", "staff_note", "approved_date",
            "booking", "decided_by_email", "decided_at", "completed_at", "created_at", "updated_at", "can_cancel",
            "can_pay",
        )

    def get_free_teachers(self, obj):
        return services.free_teachers(obj.students, obj.teachers)

    def get_can_cancel(self, obj):
        return obj.status == SchoolTrip.Status.SUBMITTED

    def get_can_pay(self, obj):
        b = obj.booking
        return bool(obj.status == SchoolTrip.Status.APPROVED and b and b.status == b.Status.PENDING
                    and not b.is_hold_expired)


class SchoolTripCreateSerializer(ClassSizeMixin, serializers.ModelSerializer):
    museum = serializers.SlugRelatedField(slug_field="slug", queryset=Museum.objects.filter(is_active=True))

    class Meta:
        model = SchoolTrip
        fields = (
            "museum", "preferred_date", "alternative_date", "slot_preference", "grades", "students",
            "young_students", "teachers", "helpers", "accessibility_needs", "guide_language", "notes",
        )

    def validate(self, attrs):
        museum = attrs["museum"]
        from museums.groups import group_block_reason

        reason = group_block_reason(museum, "school")
        if reason:
            raise serializers.ValidationError({"museum": reason})
        error = services.visit_day_error(museum, attrs["preferred_date"])
        if error:
            raise serializers.ValidationError({"preferred_date": error})
        alt = attrs.get("alternative_date")
        if alt:
            if alt == attrs["preferred_date"]:
                raise serializers.ValidationError({"alternative_date": "Pick a different day from the preferred date."})
            error = services.visit_day_error(museum, alt)
            if error:
                raise serializers.ValidationError({"alternative_date": error})
        self.check_class(attrs)
        return attrs


class ApproveSerializer(serializers.Serializer):
    date = serializers.DateField(required=False, help_text="The preferred (default) or the alternative date")
    slot = serializers.PrimaryKeyRelatedField(queryset=TimeSlot.objects.filter(is_active=True), required=False,
                                              allow_null=True)
    quoted_amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal(0), required=False,
                                             allow_null=True)
    staff_note = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class DeclineSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)
