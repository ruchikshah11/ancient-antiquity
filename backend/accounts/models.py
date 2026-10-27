from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).strip().lower(), **extra)  # case-insensitive logins
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        VISITOR = "visitor", "Visitor"
        STAFF = "staff", "Museum Staff"
        ADMIN = "admin", "Administrator"
        AGENT = "agent", "Tour operator / travel agent"  # partners app: books on account, not a panel user
        KIOSK = "kiosk", "Self-service kiosk"  # partners app: unattended device account, not a panel user
        PARTNER = "partner", "Place partner"  # read-only partner portal for a place's management, not a panel user

    username = None
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VISITOR)
    # Sign-in extras: Google account link and two-step verification (authenticator app).
    google_sub = models.CharField(max_length=64, blank=True, db_index=True, help_text="Google account id once linked")
    totp_secret = models.CharField(max_length=64, blank=True, help_text="Authenticator secret; never exposed by the API")
    totp_enabled = models.BooleanField(default=False)
    totp_backup_codes = models.JSONField(default=list, blank=True, help_text="Keyed hashes of unused backup codes")
    # Places a partner (role partner) may see in the read-only partner portal. Deliberately separate from
    # Museum.staff: that list grants selling, gate scanning and staff actions to anyone on it.
    partner_places = models.ManyToManyField(
        "museums.Museum", blank=True, related_name="partner_users",
        help_text="Partner portal: the places whose figures this partner may see",
    )
    is_sample = models.BooleanField(
        default=False, db_index=True,
        help_text="Sample-data account (seed_demo_data). Never emailed, texted or pushed, even with real providers.",
    )

    class Meta(AbstractUser.Meta):
        indexes = [models.Index(fields=["-date_joined"], name="user_joined_idx"), models.Index(fields=["role", "-date_joined"], name="user_role_joined_idx")]

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def is_panel_user(self):
        """Staff and admins can open the admin panel."""
        return self.is_superuser or self.role in (self.Role.STAFF, self.Role.ADMIN)

    @property
    def is_partner(self):
        """A place's management: read-only partner portal for partner_places."""
        return self.role == self.Role.PARTNER

    @property
    def is_admin_role(self):
        return self.is_superuser or self.role == self.Role.ADMIN


class LoginOTP(models.Model):
    """A one-time sign-in code sent by email or SMS. Only a keyed hash of the code is stored."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    destination = models.CharField(max_length=254, db_index=True, help_text="Lower-cased email or normalised phone")
    channel = models.CharField(max_length=5, choices=Channel.choices)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "login code"

    def __str__(self):
        return f"{self.channel} code for {self.destination}"
