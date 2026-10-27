from rest_framework.permissions import BasePermission


class IsPanelUser(BasePermission):
    """Museum staff or administrators."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_panel_user)


class IsAdminRole(BasePermission):
    """Administrators only."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_admin_role)


class IsApprovedAgent(BasePermission):
    """Tour operators / travel agents whose partner application has been approved."""

    message = "Only approved tour operators can do this."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.role == user.Role.AGENT):
            return False
        profile = getattr(user, "agent_profile", None)
        return bool(profile and profile.is_approved)


class IsKioskDevice(BasePermission):
    """A self-service kiosk account with an active kiosk device record."""

    message = "This screen is for self-service kiosk accounts."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.role == user.Role.KIOSK):
            return False
        device = getattr(user, "kiosk_device", None)
        return bool(device and device.is_active)


class IsPartner(BasePermission):
    """A place partner (role partner): the read-only partner portal for their own places."""

    message = "This page is for place partners."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.role == user.Role.PARTNER)
