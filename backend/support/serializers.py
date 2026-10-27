from rest_framework import serializers

from .models import ContactMessage


class ContactMessageCreateSerializer(serializers.ModelSerializer):
    # Honeypot: hidden on the page, so real visitors leave it empty; many bots fill it.
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = ContactMessage
        fields = ("id", "name", "email", "phone", "topic", "place_slug", "booking_reference", "message", "website")
        read_only_fields = ("id",)

    def validate_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Please enter your name.")
        return value

    def validate_message(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError("Please write at least a few words (10+ characters).")
        return value

    def validate_phone(self, value):
        value = value.strip()
        digits = [c for c in value if c.isdigit()]
        if value and not 8 <= len(digits) <= 15:
            raise serializers.ValidationError("Enter a valid phone number or leave it empty.")
        return value


class AdminContactMessageSerializer(serializers.ModelSerializer):
    topic_label = serializers.CharField(source="get_topic_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True, default=None)

    class Meta:
        model = ContactMessage
        fields = (
            "id", "name", "email", "phone", "topic", "topic_label", "place_slug", "booking_reference",
            "message", "status", "status_label", "admin_note", "user_email", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "name", "email", "phone", "topic", "topic_label", "place_slug", "booking_reference",
            "message", "status_label", "user_email", "created_at", "updated_at",
        )
