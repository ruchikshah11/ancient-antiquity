-- Ancient Antiquity database schema (SQLite). Data: ancient_antiquity.sql.xz.part* (see README.md)

CREATE TABLE "accounts_loginotp" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "destination" varchar(254) NOT NULL, "channel" varchar(5) NOT NULL, "code_hash" varchar(128) NOT NULL, "expires_at" datetime NOT NULL, "attempts" smallint unsigned NOT NULL CHECK ("attempts" >= 0), "used_at" datetime NULL, "created_at" datetime NOT NULL);

CREATE TABLE "accounts_user" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "password" varchar(128) NOT NULL, "last_login" datetime NULL, "is_superuser" bool NOT NULL, "first_name" varchar(150) NOT NULL, "last_name" varchar(150) NOT NULL, "is_staff" bool NOT NULL, "is_active" bool NOT NULL, "date_joined" datetime NOT NULL, "email" varchar(254) NOT NULL UNIQUE, "phone" varchar(15) NOT NULL, "role" varchar(10) NOT NULL, "google_sub" varchar(64) NOT NULL, "totp_backup_codes" text NOT NULL CHECK ((JSON_VALID("totp_backup_codes") OR "totp_backup_codes" IS NULL)), "totp_enabled" bool NOT NULL, "totp_secret" varchar(64) NOT NULL, "is_sample" bool NOT NULL);

CREATE TABLE "accounts_user_groups" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "accounts_user_partner_places" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "accounts_user_user_permissions" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "addons_addon" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(80) NOT NULL, "description" varchar(255) NOT NULL, "kind" varchar(12) NOT NULL, "price" decimal NOT NULL, "per" varchar(8) NOT NULL, "max_per_booking" smallint unsigned NULL CHECK ("max_per_booking" >= 0), "daily_stock" integer unsigned NULL CHECK ("daily_stock" >= 0), "is_active" bool NOT NULL, "sort" smallint unsigned NOT NULL CHECK ("sort" >= 0), "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "analytics_emailoptout" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "email" varchar(254) NOT NULL UNIQUE, "created_at" datetime NOT NULL);

CREATE TABLE "analytics_funnelevent" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "session_id" varchar(64) NOT NULL, "event" varchar(20) NOT NULL, "utm_source" varchar(60) NOT NULL, "utm_medium" varchar(60) NOT NULL, "utm_campaign" varchar(80) NOT NULL, "created_at" datetime NOT NULL, "booking_id" bigint NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "analytics_recoveryemail" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "email" varchar(254) NOT NULL, "sent_at" datetime NOT NULL, "booking_id" bigint NOT NULL UNIQUE REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "converted_booking_id" bigint NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "assistant_assistantlog" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "ip_hash" varchar(64) NOT NULL, "lang" varchar(5) NOT NULL, "model" varchar(60) NOT NULL, "outcome" varchar(8) NOT NULL, "tokens_in" integer unsigned NOT NULL CHECK ("tokens_in" >= 0), "tokens_out" integer unsigned NOT NULL CHECK ("tokens_out" >= 0), "cache_read_tokens" integer unsigned NOT NULL CHECK ("cache_read_tokens" >= 0), "cache_write_tokens" integer unsigned NOT NULL CHECK ("cache_write_tokens" >= 0), "tool_calls" smallint unsigned NOT NULL CHECK ("tool_calls" >= 0), "created_at" datetime NOT NULL, "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "audit_auditentry" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "at" datetime NOT NULL, "ip" char(39) NULL, "method" varchar(10) NOT NULL, "path" varchar(500) NOT NULL, "action" varchar(15) NOT NULL, "object_repr" varchar(255) NOT NULL, "status_code" smallint unsigned NULL CHECK ("status_code" >= 0), "changes" text NOT NULL CHECK ((JSON_VALID("changes") OR "changes" IS NULL)), "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "auth_group" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(150) NOT NULL UNIQUE);

CREATE TABLE "auth_group_permissions" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "group_id" integer NOT NULL REFERENCES "auth_group" ("id") DEFERRABLE INITIALLY DEFERRED, "permission_id" integer NOT NULL REFERENCES "auth_permission" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "auth_permission" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "content_type_id" integer NOT NULL REFERENCES "django_content_type" ("id") DEFERRABLE INITIALLY DEFERRED, "codename" varchar(100) NOT NULL, "name" varchar(255) NOT NULL);

CREATE VIRTUAL TABLE booking_search USING fts5(name, org, place, email, phone, tail, tokenize = 'unicode61 remove_diacritics 2', prefix = '2 3');

CREATE TABLE 'booking_search_config'(k PRIMARY KEY, v) WITHOUT ROWID;

CREATE TABLE 'booking_search_content'(id INTEGER PRIMARY KEY, c0, c1, c2, c3, c4, c5);

CREATE TABLE 'booking_search_data'(id INTEGER PRIMARY KEY, block BLOB);

CREATE TABLE 'booking_search_docsize'(id INTEGER PRIMARY KEY, sz BLOB);

CREATE TABLE 'booking_search_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;

CREATE TABLE "bookings_booking" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "reference" varchar(12) NOT NULL UNIQUE, "visit_date" date NOT NULL, "status" varchar(12) NOT NULL, "total_visitors" integer unsigned NOT NULL CHECK ("total_visitors" >= 0), "total_amount" decimal NOT NULL, "visitor_name" varchar(120) NOT NULL, "visitor_email" varchar(254) NOT NULL, "visitor_phone" varchar(15) NOT NULL, "payment_method" varchar(15) NOT NULL, "payment_id" varchar(40) NOT NULL, "created_at" datetime NOT NULL, "paid_at" datetime NULL, "cancelled_at" datetime NULL, "checked_in_at" datetime NULL, "checked_in_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "slot_id" bigint NULL REFERENCES "museums_timeslot" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "channel" varchar(10) NOT NULL, "sold_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "discount_amount" decimal NOT NULL, "escort_count" smallint unsigned NOT NULL CHECK ("escort_count" >= 0), "group_type" varchar(15) NOT NULL, "is_group" bool NOT NULL, "organisation_name" varchar(150) NOT NULL, "visitors_arrived" integer unsigned NOT NULL CHECK ("visitors_arrived" >= 0), "gateway" varchar(12) NOT NULL, "gateway_order_id" varchar(40) NOT NULL, "refund_amount" decimal NOT NULL, "refund_id" varchar(40) NOT NULL, "refund_status" varchar(10) NOT NULL, "group_request_id" bigint NULL REFERENCES "grouprequests_grouprequest" ("id") DEFERRABLE INITIALLY DEFERRED, "pay_by" datetime NULL, "promo_code_id" bigint NULL REFERENCES "promotions_promocode" ("id") DEFERRABLE INITIALLY DEFERRED, "promo_discount" decimal NOT NULL, "voucher_amount" decimal NOT NULL, "agent_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "commission_amount" decimal NOT NULL, "event_session_id" bigint NULL REFERENCES "events_eventsession" ("id") DEFERRABLE INITIALLY DEFERRED, "addons_amount" decimal NOT NULL, "membership_id" bigint NULL REFERENCES "memberships_membership" ("id") DEFERRABLE INITIALLY DEFERRED, "membership_discount" decimal NOT NULL);

CREATE TABLE "bookings_bookingaddon" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(80) NOT NULL, "kind" varchar(12) NOT NULL, "quantity" integer unsigned NOT NULL CHECK ("quantity" >= 0), "unit_price" decimal NOT NULL, "addon_id" bigint NOT NULL REFERENCES "addons_addon" ("id") DEFERRABLE INITIALLY DEFERRED, "booking_id" bigint NOT NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "bookings_bookingitem" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "ticket_name" varchar(60) NOT NULL, "quantity" integer unsigned NOT NULL CHECK ("quantity" >= 0), "unit_price" decimal NOT NULL, "booking_id" bigint NOT NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "event_price_id" bigint NULL REFERENCES "events_eventprice" ("id") DEFERRABLE INITIALLY DEFERRED, "ticket_type_id" bigint NULL REFERENCES "museums_tickettype" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "bookings_gatescan" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "admitted" integer unsigned NOT NULL CHECK ("admitted" >= 0), "scanned_at" datetime NOT NULL, "scan_id" varchar(40) NULL UNIQUE, "offline" bool NOT NULL, "booking_id" bigint NOT NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "scanned_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "gate_id" bigint NULL REFERENCES "museums_gate" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "django_admin_log" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "object_id" text NULL, "object_repr" varchar(200) NOT NULL, "action_flag" smallint unsigned NOT NULL CHECK ("action_flag" >= 0), "change_message" text NOT NULL, "content_type_id" integer NULL REFERENCES "django_content_type" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "action_time" datetime NOT NULL);

CREATE TABLE "django_content_type" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "app_label" varchar(100) NOT NULL, "model" varchar(100) NOT NULL);

CREATE TABLE "django_migrations" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "app" varchar(255) NOT NULL, "name" varchar(255) NOT NULL, "applied" datetime NOT NULL);

CREATE TABLE "django_session" ("session_key" varchar(40) NOT NULL PRIMARY KEY, "session_data" text NOT NULL, "expire_date" datetime NOT NULL);

CREATE TABLE "donations_donation" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "reference" varchar(12) NOT NULL UNIQUE, "donor_name" varchar(120) NOT NULL, "donor_email" varchar(254) NOT NULL, "donor_phone" varchar(15) NOT NULL, "donor_pan" varchar(10) NOT NULL, "donor_address" varchar(300) NOT NULL, "amount" decimal NOT NULL, "wants_80g" bool NOT NULL, "status" varchar(10) NOT NULL, "receipt_number" varchar(40) NULL UNIQUE, "receipt_fy" varchar(7) NOT NULL, "receipt_seq" integer unsigned NULL CHECK ("receipt_seq" >= 0), "payment_method" varchar(15) NOT NULL, "payment_id" varchar(40) NOT NULL, "gateway" varchar(12) NOT NULL, "gateway_order_id" varchar(40) NOT NULL, "refund_id" varchar(40) NOT NULL, "created_at" datetime NOT NULL, "paid_at" datetime NULL, "refunded_at" datetime NULL, "museum_id" bigint NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "donation_unique_fy_seq" UNIQUE ("receipt_fy", "receipt_seq"));

CREATE TABLE "donations_receiptcounter" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "financial_year" varchar(7) NOT NULL UNIQUE, "last_number" integer unsigned NOT NULL CHECK ("last_number" >= 0));

CREATE TABLE "events_event" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "title" varchar(150) NOT NULL, "slug" varchar(170) NOT NULL UNIQUE, "kind" varchar(15) NOT NULL, "description" text NOT NULL, "image_url" varchar(500) NOT NULL, "language" varchar(60) NOT NULL, "duration_minutes" integer unsigned NOT NULL CHECK ("duration_minutes" >= 0), "is_active" bool NOT NULL, "featured" bool NOT NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "events_eventprice" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(60) NOT NULL, "price" decimal NOT NULL, "sort" smallint unsigned NOT NULL CHECK ("sort" >= 0), "event_id" bigint NOT NULL REFERENCES "events_event" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "events_eventsession" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "date" date NOT NULL, "start_time" time NOT NULL, "end_time" time NOT NULL, "capacity" integer unsigned NOT NULL CHECK ("capacity" >= 0), "is_active" bool NOT NULL, "event_id" bigint NOT NULL REFERENCES "events_event" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "events_waitlistentry" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "visit_date" date NOT NULL, "quantity" smallint unsigned NOT NULL CHECK ("quantity" >= 0), "status" varchar(10) NOT NULL, "notify_channels" text NOT NULL CHECK ((JSON_VALID("notify_channels") OR "notify_channels" IS NULL)), "created_at" datetime NOT NULL, "notified_at" datetime NULL, "event_session_id" bigint NULL REFERENCES "events_eventsession" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "slot_id" bigint NULL REFERENCES "museums_timeslot" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "grouprequests_grouprequest" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "preferred_date" date NOT NULL, "alternative_date" date NULL, "preferred_time" varchar(10) NOT NULL, "group_type" varchar(15) NOT NULL, "organisation_name" varchar(150) NOT NULL, "contact_name" varchar(120) NOT NULL, "contact_email" varchar(254) NOT NULL, "contact_phone" varchar(15) NOT NULL, "participants" integer unsigned NOT NULL CHECK ("participants" >= 0), "escorts" smallint unsigned NOT NULL CHECK ("escorts" >= 0), "needs_guide" bool NOT NULL, "notes" text NOT NULL, "status" varchar(12) NOT NULL, "staff_notes" text NOT NULL, "quoted_total" decimal NULL, "discount_percent" smallint unsigned NULL CHECK ("discount_percent" >= 0), "approved_date" date NULL, "decided_at" datetime NULL, "payment_mode" varchar(10) NOT NULL, "pay_by" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "decided_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "requester_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "memberships_membership" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "card_number" varchar(13) NOT NULL UNIQUE, "plan_name" varchar(100) NOT NULL, "discount_percent" smallint unsigned NOT NULL CHECK ("discount_percent" >= 0), "free_entry" bool NOT NULL, "max_visitors_per_booking" smallint unsigned NOT NULL CHECK ("max_visitors_per_booking" >= 0), "duration_days" smallint unsigned NOT NULL CHECK ("duration_days" >= 0), "holder_name" varchar(120) NOT NULL, "status" varchar(10) NOT NULL, "starts_on" date NULL, "ends_on" date NULL, "total_amount" decimal NOT NULL, "payment_method" varchar(15) NOT NULL, "payment_id" varchar(40) NOT NULL, "gateway" varchar(12) NOT NULL, "gateway_order_id" varchar(40) NOT NULL, "refund_id" varchar(40) NOT NULL, "refund_amount" decimal NOT NULL, "refund_status" varchar(10) NOT NULL, "created_at" datetime NOT NULL, "paid_at" datetime NULL, "cancelled_at" datetime NULL, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "plan_id" bigint NOT NULL REFERENCES "memberships_membershipplan" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "memberships_membershipplan" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(100) NOT NULL, "slug" varchar(120) NOT NULL UNIQUE, "description" text NOT NULL, "price" decimal NOT NULL, "duration_days" smallint unsigned NOT NULL CHECK ("duration_days" >= 0), "discount_percent" smallint unsigned NOT NULL CHECK ("discount_percent" >= 0), "free_entry" bool NOT NULL, "max_visitors_per_booking" smallint unsigned NOT NULL CHECK ("max_visitors_per_booking" >= 0), "is_active" bool NOT NULL, "sort" smallint unsigned NOT NULL CHECK ("sort" >= 0), "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL);

CREATE TABLE "memberships_membershipplan_places" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "membershipplan_id" bigint NOT NULL REFERENCES "memberships_membershipplan" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_category" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(60) NOT NULL UNIQUE, "slug" varchar(70) NOT NULL UNIQUE);

CREATE TABLE "museums_city" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(80) NOT NULL, "state_id" bigint NOT NULL REFERENCES "museums_state" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_gate" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(60) NOT NULL, "is_active" bool NOT NULL, "sort_order" smallint unsigned NOT NULL CHECK ("sort_order" >= 0), "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_museum" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(150) NOT NULL, "slug" varchar(170) NOT NULL UNIQUE, "tagline" varchar(200) NOT NULL, "description" text NOT NULL, "highlights" text NOT NULL, "address" varchar(255) NOT NULL, "latitude" decimal NULL, "longitude" decimal NULL, "image_url" varchar(500) NOT NULL, "established_year" integer unsigned NULL CHECK ("established_year" >= 0), "managed_by" varchar(150) NOT NULL, "contact_phone" varchar(20) NOT NULL, "contact_email" varchar(254) NOT NULL, "opening_time" time NOT NULL, "closing_time" time NOT NULL, "closed_weekday" integer NULL, "is_featured" bool NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "category_id" bigint NULL REFERENCES "museums_category" ("id") DEFERRABLE INITIALLY DEFERRED, "city_id" bigint NOT NULL REFERENCES "museums_city" ("id") DEFERRABLE INITIALLY DEFERRED, "image_credit" varchar(300) NOT NULL, "image_source_url" varchar(500) NOT NULL, "source_url" varchar(500) NOT NULL, "place_type" varchar(10) NOT NULL, "allow_groups" bool NOT NULL, "group_discount_percent" smallint unsigned NOT NULL CHECK ("group_discount_percent" >= 0), "school_discount_percent" smallint unsigned NOT NULL CHECK ("school_discount_percent" >= 0), "info_verified" bool NOT NULL, "info_verified_at" datetime NULL, "info_verified_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "facilities" text NOT NULL CHECK ((JSON_VALID("facilities") OR "facilities" IS NULL)), "virtual_tour_kind" varchar(20) NOT NULL, "virtual_tour_url" varchar(500) NOT NULL, "allow_individual" bool NOT NULL, google_place_id varchar(300) NOT NULL DEFAULT '', google_place_name varchar(200) NOT NULL DEFAULT '');

CREATE TABLE "museums_museum_staff" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_museumimage" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "url" varchar(500) NOT NULL, "caption" varchar(200) NOT NULL, "credit" varchar(300) NOT NULL, "source_url" varchar(500) NOT NULL, "sort_order" smallint unsigned NOT NULL CHECK ("sort_order" >= 0), "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_placeclosure" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "start_date" date NOT NULL, "end_date" date NOT NULL, "reason" varchar(200) NOT NULL, "all_day" bool NOT NULL, "created_at" datetime NOT NULL, "created_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_placeclosure_slots" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "placeclosure_id" bigint NOT NULL REFERENCES "museums_placeclosure" ("id") DEFERRABLE INITIALLY DEFERRED, "timeslot_id" bigint NOT NULL REFERENCES "museums_timeslot" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_pricerule" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(100) NOT NULL, "start_date" date NULL, "end_date" date NULL, "weekdays" varchar(20) NOT NULL, "adjustment_type" varchar(12) NOT NULL, "value" decimal NOT NULL, "priority" smallint NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "ticket_type_id" bigint NULL REFERENCES "museums_tickettype" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_review" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "rating" decimal NOT NULL, "comment" text NOT NULL, "created_at" datetime NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "is_published" bool NOT NULL, "title" varchar(120) NOT NULL, "updated_at" datetime NOT NULL, "helpful_count" integer unsigned NOT NULL CHECK ("helpful_count" >= 0));

CREATE TABLE "museums_reviewphoto" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "image" varchar(100) NOT NULL, "status" varchar(10) NOT NULL, "created_at" datetime NOT NULL, "review_id" bigint NOT NULL REFERENCES "museums_review" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_reviewvote" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "created_at" datetime NOT NULL, "review_id" bigint NOT NULL REFERENCES "museums_review" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_sitesettings" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "individual_bookings_enabled" bool NOT NULL, "group_bookings_enabled" bool NOT NULL, "group_requests_enabled" bool NOT NULL, "school_trips_enabled" bool NOT NULL, "events_enabled" bool NOT NULL, "passes_enabled" bool NOT NULL, "paused_message" varchar(200) NOT NULL, "updated_at" datetime NOT NULL, "updated_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "footer_brand" varchar(80) NOT NULL, "footer_copyright" varchar(200) NOT NULL, "footer_tagline" varchar(200) NOT NULL);

CREATE TABLE "museums_state" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(80) NOT NULL UNIQUE, "code" varchar(4) NOT NULL UNIQUE, "is_union_territory" bool NOT NULL);

CREATE TABLE "museums_tickettype" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(60) NOT NULL, "description" varchar(150) NOT NULL, "price" decimal NOT NULL, "sort_order" smallint unsigned NOT NULL CHECK ("sort_order" >= 0), "is_active" bool NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "museums_timeslot" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "start_time" time NOT NULL, "end_time" time NOT NULL, "capacity" integer unsigned NOT NULL CHECK ("capacity" >= 0), "is_active" bool NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "notifications_notificationlog" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "kind" varchar(30) NOT NULL, "recipient" varchar(254) NOT NULL, "subject" varchar(200) NOT NULL, "status" varchar(7) NOT NULL, "error" text NOT NULL, "created_at" datetime NOT NULL, "booking_id" bigint NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "channel" varchar(10) NOT NULL);

CREATE TABLE "notifications_pushsubscription" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "endpoint" varchar(1000) NOT NULL UNIQUE, "p256dh" varchar(200) NOT NULL, "auth" varchar(100) NOT NULL, "user_agent" varchar(300) NOT NULL, "created_at" datetime NOT NULL, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "partners_agentpayment" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "amount" decimal NOT NULL, "reference" varchar(80) NOT NULL, "note" varchar(255) NOT NULL, "received_on" date NOT NULL, "created_at" datetime NOT NULL, "recorded_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "agent_id" bigint NOT NULL REFERENCES "partners_agentprofile" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "partners_agentprofile" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "company_name" varchar(150) NOT NULL, "gstin" varchar(15) NOT NULL, "contact_phone" varchar(15) NOT NULL, "city" varchar(80) NOT NULL, "message" text NOT NULL, "commission_percent" decimal NOT NULL, "credit_limit" decimal NOT NULL, "balance" decimal NOT NULL, "status" varchar(10) NOT NULL, "is_approved" bool NOT NULL, "approved_at" datetime NULL, "admin_note" varchar(255) NOT NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "approved_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL UNIQUE REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "partners_kioskdevice" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(100) NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL, "created_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL UNIQUE REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "partners_kioskdevice_museums" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "kioskdevice_id" bigint NOT NULL REFERENCES "partners_kioskdevice" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "partners_partneraccount" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "account_holder" varchar(150) NOT NULL, "bank_name" varchar(100) NOT NULL, "account_number" varchar(30) NOT NULL, "ifsc" varchar(11) NOT NULL, "razorpay_account_id" varchar(40) NOT NULL, "platform_fee_percent" decimal NOT NULL, "updated_at" datetime NOT NULL, "museum_id" bigint NOT NULL UNIQUE REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "partners_settlement" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "period_start" date NOT NULL, "period_end" date NOT NULL, "booking_count" integer unsigned NOT NULL CHECK ("booking_count" >= 0), "visitor_count" integer unsigned NOT NULL CHECK ("visitor_count" >= 0), "gross_online" decimal NOT NULL, "gross_kiosk" decimal NOT NULL, "gross_counter" decimal NOT NULL, "gross_agent" decimal NOT NULL, "refunds" decimal NOT NULL, "platform_fee_percent" decimal NOT NULL, "platform_fee" decimal NOT NULL, "gst_on_fee" decimal NOT NULL, "net_payable" decimal NOT NULL, "status" varchar(10) NOT NULL, "approved_at" datetime NULL, "paid_reference" varchar(80) NOT NULL, "paid_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "approved_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "created_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "unique_settlement_period" UNIQUE ("museum_id", "period_start", "period_end"));

CREATE TABLE "passes_combopass" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(120) NOT NULL, "slug" varchar(140) NOT NULL UNIQUE, "description" text NOT NULL, "image_url" varchar(500) NOT NULL, "price_indian" decimal NOT NULL, "price_foreign" decimal NOT NULL, "price_student" decimal NOT NULL, "price_child" decimal NOT NULL, "validity_days" smallint unsigned NOT NULL CHECK ("validity_days" >= 0), "is_active" bool NOT NULL, "featured" bool NOT NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL);

CREATE TABLE "passes_combopasssite" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "sort_order" smallint unsigned NOT NULL CHECK ("sort_order" >= 0), "combo_pass_id" bigint NOT NULL REFERENCES "passes_combopass" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "passes_passorder" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "reference" varchar(12) NOT NULL UNIQUE, "pass_name" varchar(120) NOT NULL, "validity_days" smallint unsigned NOT NULL CHECK ("validity_days" >= 0), "start_date" date NOT NULL, "indian_count" smallint unsigned NOT NULL CHECK ("indian_count" >= 0), "foreign_count" smallint unsigned NOT NULL CHECK ("foreign_count" >= 0), "student_count" smallint unsigned NOT NULL CHECK ("student_count" >= 0), "child_count" smallint unsigned NOT NULL CHECK ("child_count" >= 0), "unit_prices" text NOT NULL CHECK ((JSON_VALID("unit_prices") OR "unit_prices" IS NULL)), "total_visitors" integer unsigned NOT NULL CHECK ("total_visitors" >= 0), "total_amount" decimal NOT NULL, "status" varchar(10) NOT NULL, "visitor_name" varchar(120) NOT NULL, "visitor_email" varchar(254) NOT NULL, "visitor_phone" varchar(15) NOT NULL, "payment_method" varchar(15) NOT NULL, "payment_id" varchar(40) NOT NULL, "gateway" varchar(12) NOT NULL, "gateway_order_id" varchar(40) NOT NULL, "refund_id" varchar(40) NOT NULL, "refund_amount" decimal NOT NULL, "refund_status" varchar(10) NOT NULL, "created_at" datetime NOT NULL, "paid_at" datetime NULL, "cancelled_at" datetime NULL, "combo_pass_id" bigint NOT NULL REFERENCES "passes_combopass" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "passes_passvisit" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "visited_at" datetime NOT NULL, "admitted" integer unsigned NOT NULL CHECK ("admitted" >= 0), "scan_id" varchar(40) NULL UNIQUE, "offline" bool NOT NULL, "gate_id" bigint NULL REFERENCES "museums_gate" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "order_id" bigint NOT NULL REFERENCES "passes_passorder" ("id") DEFERRABLE INITIALLY DEFERRED, "scanned_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "promotions_giftvoucher" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "code" varchar(14) NOT NULL UNIQUE, "initial_value" decimal NOT NULL, "balance" decimal NOT NULL, "purchaser_name" varchar(120) NOT NULL, "purchaser_email" varchar(254) NOT NULL, "recipient_name" varchar(120) NOT NULL, "recipient_email" varchar(254) NOT NULL, "message" text NOT NULL, "valid_until" date NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL, "issued_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "promotions_promocode" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "code" varchar(30) NOT NULL, "description" varchar(200) NOT NULL, "discount_type" varchar(10) NOT NULL, "value" decimal NOT NULL, "max_discount" decimal NULL, "min_order_amount" decimal NOT NULL, "valid_from" datetime NULL, "valid_to" datetime NULL, "usage_limit" integer unsigned NULL CHECK ("usage_limit" >= 0), "per_user_limit" integer unsigned NULL CHECK ("per_user_limit" >= 0), "scope" varchar(12) NOT NULL, "place_types" varchar(100) NOT NULL, "applies_to" varchar(10) NOT NULL, "first_booking_only" bool NOT NULL, "is_active" bool NOT NULL, "created_at" datetime NOT NULL, "created_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "promotions_promocode_museums" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "promocode_id" bigint NOT NULL REFERENCES "promotions_promocode" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "promotions_promoredemption" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "amount" decimal NOT NULL, "created_at" datetime NOT NULL, "booking_id" bigint NOT NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "code_id" bigint NOT NULL REFERENCES "promotions_promocode" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "promotions_voucherredemption" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "amount" decimal NOT NULL, "created_at" datetime NOT NULL, "reversed_at" datetime NULL, "booking_id" bigint NOT NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "voucher_id" bigint NOT NULL REFERENCES "promotions_giftvoucher" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "schools_school" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(150) NOT NULL, "board" varchar(6) NOT NULL, "udise_code" varchar(11) NOT NULL, "address" varchar(255) NOT NULL, "city" varchar(80) NOT NULL, "principal_name" varchar(120) NOT NULL, "phone" varchar(15) NOT NULL, "contact_name" varchar(120) NOT NULL, "contact_phone" varchar(15) NOT NULL, "contact_email" varchar(254) NOT NULL, "status" varchar(8) NOT NULL, "rejection_reason" text NOT NULL, "verified_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "owner_id" bigint NOT NULL UNIQUE REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "state_id" bigint NOT NULL REFERENCES "museums_state" ("id") DEFERRABLE INITIALLY DEFERRED, "verified_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "schools_schooltrip" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "preferred_date" date NOT NULL, "alternative_date" date NULL, "slot_preference" varchar(10) NOT NULL, "grades" varchar(60) NOT NULL, "students" integer unsigned NOT NULL CHECK ("students" >= 0), "young_students" integer unsigned NOT NULL CHECK ("young_students" >= 0), "teachers" smallint unsigned NOT NULL CHECK ("teachers" >= 0), "helpers" smallint unsigned NOT NULL CHECK ("helpers" >= 0), "accessibility_needs" text NOT NULL, "guide_language" varchar(2) NOT NULL, "notes" text NOT NULL, "status" varchar(10) NOT NULL, "estimated_amount" decimal NOT NULL, "quoted_amount" decimal NULL, "staff_note" text NOT NULL, "approved_date" date NULL, "decided_at" datetime NULL, "completed_at" datetime NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "booking_id" bigint NULL REFERENCES "bookings_booking" ("id") DEFERRABLE INITIALLY DEFERRED, "decided_by_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "requested_by_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED, "school_id" bigint NOT NULL REFERENCES "schools_school" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "stats_dailystat" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "date" date NOT NULL, "channel" varchar(10) NOT NULL, "is_group" bool NOT NULL, "status_group" varchar(10) NOT NULL, "bookings" integer unsigned NOT NULL CHECK ("bookings" >= 0), "checked_in_bookings" integer unsigned NOT NULL CHECK ("checked_in_bookings" >= 0), "visitors" integer unsigned NOT NULL CHECK ("visitors" >= 0), "revenue" decimal NOT NULL, "refunds" decimal NOT NULL, "discounts" decimal NOT NULL, "addons" decimal NOT NULL, "membership_discounts" decimal NOT NULL, "visit_bookings" integer unsigned NOT NULL CHECK ("visit_bookings" >= 0), "visit_visitors" integer unsigned NOT NULL CHECK ("visit_visitors" >= 0), "visit_checked_in_visitors" integer unsigned NOT NULL CHECK ("visit_checked_in_visitors" >= 0), "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, CONSTRAINT "dailystat_unique_key" UNIQUE ("date", "museum_id", "channel", "is_group", "status_group"));

CREATE TABLE "stats_exportjob" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "kind" varchar(16) NOT NULL, "filters" text NOT NULL CHECK ((JSON_VALID("filters") OR "filters" IS NULL)), "status" varchar(10) NOT NULL, "row_count" integer unsigned NOT NULL CHECK ("row_count" >= 0), "total_rows" integer unsigned NULL CHECK ("total_rows" >= 0), "file_name" varchar(200) NOT NULL, "file_path" varchar(300) NOT NULL, "file_size" bigint unsigned NOT NULL CHECK ("file_size" >= 0), "note" varchar(300) NOT NULL, "error" text NOT NULL, "created_at" datetime NOT NULL, "started_at" datetime NULL, "heartbeat_at" datetime NULL, "finished_at" datetime NULL, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "stats_statday" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "date" date NOT NULL UNIQUE, "refreshed_at" datetime NULL, "dirty_since" datetime NULL);

CREATE TABLE "support_contactmessage" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "name" varchar(120) NOT NULL, "email" varchar(254) NOT NULL, "phone" varchar(20) NOT NULL, "topic" varchar(20) NOT NULL, "place_slug" varchar(220) NOT NULL, "booking_reference" varchar(40) NOT NULL, "message" text NOT NULL, "status" varchar(12) NOT NULL, "admin_note" text NOT NULL, "ip_address" char(39) NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "user_id" bigint NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "trips_favourite" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "created_at" datetime NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "trips_trip" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "title" varchar(120) NOT NULL, "start_date" date NULL, "end_date" date NULL, "notes" text NOT NULL, "created_at" datetime NOT NULL, "updated_at" datetime NOT NULL, "user_id" bigint NOT NULL REFERENCES "accounts_user" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE TABLE "trips_tripstop" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "day" smallint unsigned NOT NULL CHECK ("day" >= 0), "order" smallint unsigned NOT NULL CHECK ("order" >= 0), "planned_time" time NULL, "notes" varchar(300) NOT NULL, "museum_id" bigint NOT NULL REFERENCES "museums_museum" ("id") DEFERRABLE INITIALLY DEFERRED, "trip_id" bigint NOT NULL REFERENCES "trips_trip" ("id") DEFERRABLE INITIALLY DEFERRED);

CREATE INDEX "accounts_loginotp_created_at_c56be1ca" ON "accounts_loginotp" ("created_at");

CREATE INDEX "accounts_loginotp_destination_462277ef" ON "accounts_loginotp" ("destination");

CREATE INDEX "accounts_user_google_sub_8c9d6bcc" ON "accounts_user" ("google_sub");

CREATE INDEX "accounts_user_groups_group_id_bd11a704" ON "accounts_user_groups" ("group_id");

CREATE INDEX "accounts_user_groups_user_id_52b62117" ON "accounts_user_groups" ("user_id");

CREATE UNIQUE INDEX "accounts_user_groups_user_id_group_id_59c0b32f_uniq" ON "accounts_user_groups" ("user_id", "group_id");

CREATE INDEX "accounts_user_is_sample_bca1af60" ON "accounts_user" ("is_sample");

CREATE INDEX "accounts_user_partner_places_museum_id_9c23eab5" ON "accounts_user_partner_places" ("museum_id");

CREATE INDEX "accounts_user_partner_places_user_id_8b10aa26" ON "accounts_user_partner_places" ("user_id");

CREATE UNIQUE INDEX "accounts_user_partner_places_user_id_museum_id_e02f45e6_uniq" ON "accounts_user_partner_places" ("user_id", "museum_id");

CREATE INDEX "accounts_user_user_permissions_permission_id_113bb443" ON "accounts_user_user_permissions" ("permission_id");

CREATE INDEX "accounts_user_user_permissions_user_id_e4f0a161" ON "accounts_user_user_permissions" ("user_id");

CREATE UNIQUE INDEX "accounts_user_user_permissions_user_id_permission_id_2ab516c2_uniq" ON "accounts_user_user_permissions" ("user_id", "permission_id");

CREATE INDEX "addons_addon_museum_id_80204ba8" ON "addons_addon" ("museum_id");

CREATE INDEX "analytics_f_event_697ecd_idx" ON "analytics_funnelevent" ("event", "created_at");

CREATE INDEX "analytics_f_museum__373f08_idx" ON "analytics_funnelevent" ("museum_id", "event");

CREATE INDEX "analytics_funnelevent_booking_id_c52022eb" ON "analytics_funnelevent" ("booking_id");

CREATE INDEX "analytics_funnelevent_created_at_0e7f3c0e" ON "analytics_funnelevent" ("created_at");

CREATE INDEX "analytics_funnelevent_event_88f855f9" ON "analytics_funnelevent" ("event");

CREATE INDEX "analytics_funnelevent_museum_id_dc4c88f2" ON "analytics_funnelevent" ("museum_id");

CREATE INDEX "analytics_funnelevent_session_id_8d6f7e3f" ON "analytics_funnelevent" ("session_id");

CREATE INDEX "analytics_funnelevent_user_id_1a35299b" ON "analytics_funnelevent" ("user_id");

CREATE INDEX "analytics_recoveryemail_converted_booking_id_c3a9fccf" ON "analytics_recoveryemail" ("converted_booking_id");

CREATE INDEX "analytics_recoveryemail_sent_at_a1dd161e" ON "analytics_recoveryemail" ("sent_at");

CREATE INDEX "assistant_assistantlog_created_at_d96f11ee" ON "assistant_assistantlog" ("created_at");

CREATE INDEX "assistant_assistantlog_ip_hash_0da20c21" ON "assistant_assistantlog" ("ip_hash");

CREATE INDEX "assistant_assistantlog_user_id_220b5ec5" ON "assistant_assistantlog" ("user_id");

CREATE INDEX "audit_auditentry_action_dee621eb" ON "audit_auditentry" ("action");

CREATE INDEX "audit_auditentry_at_09f867ec" ON "audit_auditentry" ("at");

CREATE INDEX "audit_auditentry_user_id_b5ee03cd" ON "audit_auditentry" ("user_id");

CREATE INDEX "auth_group_permissions_group_id_b120cbf9" ON "auth_group_permissions" ("group_id");

CREATE UNIQUE INDEX "auth_group_permissions_group_id_permission_id_0cd325b0_uniq" ON "auth_group_permissions" ("group_id", "permission_id");

CREATE INDEX "auth_group_permissions_permission_id_84c5c92e" ON "auth_group_permissions" ("permission_id");

CREATE INDEX "auth_permission_content_type_id_2f476e4b" ON "auth_permission" ("content_type_id");

CREATE UNIQUE INDEX "auth_permission_content_type_id_codename_01ab375a_uniq" ON "auth_permission" ("content_type_id", "codename");

CREATE INDEX "booking_created_idx" ON "bookings_booking" ("created_at" DESC);

CREATE INDEX "booking_museum_paid_idx" ON "bookings_booking" ("museum_id", "paid_at");

CREATE INDEX "booking_museum_status_idx" ON "bookings_booking" ("museum_id", "status", "created_at");

CREATE INDEX booking_stats_created_idx ON bookings_booking (created_at, museum_id, channel, is_group, status, total_visitors, total_amount, refund_amount, discount_amount, addons_amount, membership_discount);

CREATE INDEX booking_stats_visit_idx ON bookings_booking (visit_date, museum_id, channel, is_group, status, total_visitors);

CREATE INDEX "booking_status_created_idx" ON "bookings_booking" ("status", "created_at");

CREATE INDEX "booking_status_visit_idx" ON "bookings_booking" ("status", "visit_date");

CREATE INDEX "booking_totals_idx" ON "bookings_booking" ("status", "museum_id", "channel", "total_amount", "total_visitors");

CREATE INDEX "booking_user_created_idx" ON "bookings_booking" ("user_id", "created_at" DESC);

CREATE INDEX "bookings_bo_museum__b65710_idx" ON "bookings_booking" ("museum_id", "visit_date", "slot_id");

CREATE INDEX "bookings_booking_agent_id_c8b99208" ON "bookings_booking" ("agent_id");

CREATE INDEX "bookings_booking_channel_678d60b8" ON "bookings_booking" ("channel");

CREATE INDEX "bookings_booking_checked_in_by_id_376f8204" ON "bookings_booking" ("checked_in_by_id");

CREATE INDEX "bookings_booking_event_session_id_028d932d" ON "bookings_booking" ("event_session_id");

CREATE INDEX "bookings_booking_gateway_order_id_dea6e78d" ON "bookings_booking" ("gateway_order_id");

CREATE INDEX "bookings_booking_group_request_id_d8202668" ON "bookings_booking" ("group_request_id");

CREATE INDEX "bookings_booking_is_group_ca2dc1bc" ON "bookings_booking" ("is_group");

CREATE INDEX "bookings_booking_membership_id_b4647465" ON "bookings_booking" ("membership_id");

CREATE INDEX "bookings_booking_museum_id_14f1d170" ON "bookings_booking" ("museum_id");

CREATE INDEX "bookings_booking_promo_code_id_0e234c68" ON "bookings_booking" ("promo_code_id");

CREATE INDEX "bookings_booking_slot_id_53c8e8ac" ON "bookings_booking" ("slot_id");

CREATE INDEX "bookings_booking_sold_by_id_05f22d92" ON "bookings_booking" ("sold_by_id");

CREATE INDEX "bookings_booking_status_380c5cb8" ON "bookings_booking" ("status");

CREATE INDEX "bookings_booking_user_id_834dfc23" ON "bookings_booking" ("user_id");

CREATE INDEX "bookings_booking_visit_date_70ff7e31" ON "bookings_booking" ("visit_date");

CREATE INDEX "bookings_bookingaddon_addon_id_f051e6c7" ON "bookings_bookingaddon" ("addon_id");

CREATE INDEX "bookings_bookingaddon_booking_id_a307a27b" ON "bookings_bookingaddon" ("booking_id");

CREATE INDEX "bookings_bookingitem_booking_id_23e975dd" ON "bookings_bookingitem" ("booking_id");

CREATE INDEX "bookings_bookingitem_event_price_id_430e58a5" ON "bookings_bookingitem" ("event_price_id");

CREATE INDEX "bookings_bookingitem_ticket_type_id_dc1c5a3a" ON "bookings_bookingitem" ("ticket_type_id");

CREATE INDEX "bookings_gatescan_booking_id_0cdee05d" ON "bookings_gatescan" ("booking_id");

CREATE INDEX "bookings_gatescan_gate_id_89801079" ON "bookings_gatescan" ("gate_id");

CREATE INDEX "bookings_gatescan_scanned_by_id_8d92550f" ON "bookings_gatescan" ("scanned_by_id");

CREATE INDEX "dailystat_dashboard_idx" ON "stats_dailystat" ("museum_id", "channel", "is_group", "status_group", "bookings", "checked_in_bookings", "visitors", "revenue");

CREATE INDEX "dailystat_group_date_idx" ON "stats_dailystat" ("status_group", "date");

CREATE INDEX "dailystat_museum_date_idx" ON "stats_dailystat" ("museum_id", "date");

CREATE INDEX "django_admin_log_content_type_id_c4bce8eb" ON "django_admin_log" ("content_type_id");

CREATE INDEX "django_admin_log_user_id_c564eba6" ON "django_admin_log" ("user_id");

CREATE UNIQUE INDEX "django_content_type_app_label_model_76bd3d3b_uniq" ON "django_content_type" ("app_label", "model");

CREATE INDEX "django_session_expire_date_a5c62663" ON "django_session" ("expire_date");

CREATE INDEX "donations_donation_gateway_order_id_e9c3a4b2" ON "donations_donation" ("gateway_order_id");

CREATE INDEX "donations_donation_museum_id_c202619c" ON "donations_donation" ("museum_id");

CREATE INDEX "donations_donation_paid_at_39ad50ac" ON "donations_donation" ("paid_at");

CREATE INDEX "donations_donation_status_6c73bb41" ON "donations_donation" ("status");

CREATE INDEX "donations_donation_user_id_04dd09bd" ON "donations_donation" ("user_id");

CREATE INDEX "events_event_kind_6e85e911" ON "events_event" ("kind");

CREATE INDEX "events_event_museum_id_b42bc6ed" ON "events_event" ("museum_id");

CREATE INDEX "events_eventprice_event_id_62a4619a" ON "events_eventprice" ("event_id");

CREATE INDEX "events_eventsession_date_45b2e2ea" ON "events_eventsession" ("date");

CREATE INDEX "events_eventsession_event_id_0fdc500c" ON "events_eventsession" ("event_id");

CREATE INDEX "events_waitlistentry_event_session_id_ba88242d" ON "events_waitlistentry" ("event_session_id");

CREATE INDEX "events_waitlistentry_museum_id_2ee88243" ON "events_waitlistentry" ("museum_id");

CREATE INDEX "events_waitlistentry_slot_id_133c0b57" ON "events_waitlistentry" ("slot_id");

CREATE INDEX "events_waitlistentry_status_05c3f996" ON "events_waitlistentry" ("status");

CREATE INDEX "events_waitlistentry_user_id_9701a4f3" ON "events_waitlistentry" ("user_id");

CREATE INDEX "events_waitlistentry_visit_date_aa0e4a02" ON "events_waitlistentry" ("visit_date");

CREATE INDEX "exportjob_user_created_idx" ON "stats_exportjob" ("user_id", "created_at" DESC);

CREATE INDEX "gatescan_scanned_idx" ON "bookings_gatescan" ("scanned_at");

CREATE INDEX "grouprequests_grouprequest_decided_by_id_5dca59a4" ON "grouprequests_grouprequest" ("decided_by_id");

CREATE INDEX "grouprequests_grouprequest_museum_id_a200bc55" ON "grouprequests_grouprequest" ("museum_id");

CREATE INDEX "grouprequests_grouprequest_preferred_date_688bf9e0" ON "grouprequests_grouprequest" ("preferred_date");

CREATE INDEX "grouprequests_grouprequest_requester_id_44b1259a" ON "grouprequests_grouprequest" ("requester_id");

CREATE INDEX "grouprequests_grouprequest_status_c8570989" ON "grouprequests_grouprequest" ("status");

CREATE INDEX "memberships_membership_ends_on_9099c3ea" ON "memberships_membership" ("ends_on");

CREATE INDEX "memberships_membership_gateway_order_id_26ed5842" ON "memberships_membership" ("gateway_order_id");

CREATE INDEX "memberships_membership_plan_id_a999e2c0" ON "memberships_membership" ("plan_id");

CREATE INDEX "memberships_membership_status_8a081711" ON "memberships_membership" ("status");

CREATE INDEX "memberships_membership_user_id_1de5976a" ON "memberships_membership" ("user_id");

CREATE INDEX "memberships_membershipplan_places_membershipplan_id_b8d07293" ON "memberships_membershipplan_places" ("membershipplan_id");

CREATE UNIQUE INDEX "memberships_membershipplan_places_membershipplan_id_museum_id_6448e5ed_uniq" ON "memberships_membershipplan_places" ("membershipplan_id", "museum_id");

CREATE INDEX "memberships_membershipplan_places_museum_id_946c5964" ON "memberships_membershipplan_places" ("museum_id");

CREATE UNIQUE INDEX "museums_city_name_state_id_520789b4_uniq" ON "museums_city" ("name", "state_id");

CREATE INDEX "museums_city_state_id_7ea5ebde" ON "museums_city" ("state_id");

CREATE INDEX "museums_gate_museum_id_4f2814c4" ON "museums_gate" ("museum_id");

CREATE UNIQUE INDEX "museums_gate_museum_id_name_44b0dce7_uniq" ON "museums_gate" ("museum_id", "name");

CREATE INDEX "museums_museum_category_id_4955bcb8" ON "museums_museum" ("category_id");

CREATE INDEX "museums_museum_city_id_5da8f524" ON "museums_museum" ("city_id");

CREATE INDEX "museums_museum_info_verified_by_id_eb1d3d05" ON "museums_museum" ("info_verified_by_id");

CREATE INDEX "museums_museum_place_type_7f79b8a1" ON "museums_museum" ("place_type");

CREATE INDEX "museums_museum_staff_museum_id_5f998293" ON "museums_museum_staff" ("museum_id");

CREATE UNIQUE INDEX "museums_museum_staff_museum_id_user_id_eccb8b6e_uniq" ON "museums_museum_staff" ("museum_id", "user_id");

CREATE INDEX "museums_museum_staff_user_id_3239f0f7" ON "museums_museum_staff" ("user_id");

CREATE INDEX "museums_museumimage_museum_id_46b54501" ON "museums_museumimage" ("museum_id");

CREATE INDEX "museums_placeclosure_created_by_id_bd265f2c" ON "museums_placeclosure" ("created_by_id");

CREATE INDEX "museums_placeclosure_end_date_8b5f6611" ON "museums_placeclosure" ("end_date");

CREATE INDEX "museums_placeclosure_museum_id_a6316db4" ON "museums_placeclosure" ("museum_id");

CREATE INDEX "museums_placeclosure_slots_placeclosure_id_18c05456" ON "museums_placeclosure_slots" ("placeclosure_id");

CREATE UNIQUE INDEX "museums_placeclosure_slots_placeclosure_id_timeslot_id_22cb0fb3_uniq" ON "museums_placeclosure_slots" ("placeclosure_id", "timeslot_id");

CREATE INDEX "museums_placeclosure_slots_timeslot_id_7322604b" ON "museums_placeclosure_slots" ("timeslot_id");

CREATE INDEX "museums_placeclosure_start_date_f0ed8f15" ON "museums_placeclosure" ("start_date");

CREATE INDEX "museums_pricerule_museum_id_31cd1d3a" ON "museums_pricerule" ("museum_id");

CREATE INDEX "museums_pricerule_ticket_type_id_4b990cf4" ON "museums_pricerule" ("ticket_type_id");

CREATE INDEX "museums_review_museum_id_b42236ee" ON "museums_review" ("museum_id");

CREATE UNIQUE INDEX "museums_review_museum_id_user_id_cfc35e2f_uniq" ON "museums_review" ("museum_id", "user_id");

CREATE INDEX "museums_review_user_id_9a29babb" ON "museums_review" ("user_id");

CREATE INDEX "museums_reviewphoto_review_id_43b46e35" ON "museums_reviewphoto" ("review_id");

CREATE INDEX "museums_reviewphoto_status_e92f503e" ON "museums_reviewphoto" ("status");

CREATE INDEX "museums_reviewvote_review_id_e1809a4f" ON "museums_reviewvote" ("review_id");

CREATE UNIQUE INDEX "museums_reviewvote_review_id_user_id_2ef36e9d_uniq" ON "museums_reviewvote" ("review_id", "user_id");

CREATE INDEX "museums_reviewvote_user_id_a456909e" ON "museums_reviewvote" ("user_id");

CREATE INDEX "museums_sitesettings_updated_by_id_c5c4546b" ON "museums_sitesettings" ("updated_by_id");

CREATE INDEX "museums_tickettype_museum_id_afce765f" ON "museums_tickettype" ("museum_id");

CREATE INDEX "museums_timeslot_museum_id_05bc5ef3" ON "museums_timeslot" ("museum_id");

CREATE INDEX "notifications_notificationlog_booking_id_664f7b4f" ON "notifications_notificationlog" ("booking_id");

CREATE INDEX "notifications_notificationlog_created_at_d5a0fcfb" ON "notifications_notificationlog" ("created_at");

CREATE INDEX "notifications_notificationlog_kind_71723e14" ON "notifications_notificationlog" ("kind");

CREATE INDEX "notifications_notificationlog_status_167f7719" ON "notifications_notificationlog" ("status");

CREATE INDEX "notifications_notificationlog_user_id_ea3d4e7c" ON "notifications_notificationlog" ("user_id");

CREATE INDEX "notifications_pushsubscription_user_id_ffe8030a" ON "notifications_pushsubscription" ("user_id");

CREATE INDEX "partners_agentpayment_agent_id_28209029" ON "partners_agentpayment" ("agent_id");

CREATE INDEX "partners_agentpayment_recorded_by_id_5e1bbae0" ON "partners_agentpayment" ("recorded_by_id");

CREATE INDEX "partners_agentprofile_approved_by_id_e5eaef82" ON "partners_agentprofile" ("approved_by_id");

CREATE INDEX "partners_agentprofile_status_6169ca94" ON "partners_agentprofile" ("status");

CREATE INDEX "partners_kioskdevice_created_by_id_b9e85091" ON "partners_kioskdevice" ("created_by_id");

CREATE INDEX "partners_kioskdevice_museums_kioskdevice_id_fd8b5383" ON "partners_kioskdevice_museums" ("kioskdevice_id");

CREATE UNIQUE INDEX "partners_kioskdevice_museums_kioskdevice_id_museum_id_82bb4ef5_uniq" ON "partners_kioskdevice_museums" ("kioskdevice_id", "museum_id");

CREATE INDEX "partners_kioskdevice_museums_museum_id_22ac54a3" ON "partners_kioskdevice_museums" ("museum_id");

CREATE INDEX "partners_settlement_approved_by_id_1717975f" ON "partners_settlement" ("approved_by_id");

CREATE INDEX "partners_settlement_created_by_id_ae68e74c" ON "partners_settlement" ("created_by_id");

CREATE INDEX "partners_settlement_museum_id_d1720480" ON "partners_settlement" ("museum_id");

CREATE INDEX "partners_settlement_status_50de9352" ON "partners_settlement" ("status");

CREATE INDEX "passes_combopasssite_combo_pass_id_2934ae7c" ON "passes_combopasssite" ("combo_pass_id");

CREATE UNIQUE INDEX "passes_combopasssite_combo_pass_id_museum_id_fbc1718b_uniq" ON "passes_combopasssite" ("combo_pass_id", "museum_id");

CREATE INDEX "passes_combopasssite_museum_id_862d5d92" ON "passes_combopasssite" ("museum_id");

CREATE INDEX "passes_passorder_combo_pass_id_0fb570fc" ON "passes_passorder" ("combo_pass_id");

CREATE INDEX "passes_passorder_gateway_order_id_b49cdef0" ON "passes_passorder" ("gateway_order_id");

CREATE INDEX "passes_passorder_start_date_7d05837a" ON "passes_passorder" ("start_date");

CREATE INDEX "passes_passorder_status_53e6adbe" ON "passes_passorder" ("status");

CREATE INDEX "passes_passorder_user_id_856a665f" ON "passes_passorder" ("user_id");

CREATE INDEX "passes_passvisit_gate_id_e2538d57" ON "passes_passvisit" ("gate_id");

CREATE INDEX "passes_passvisit_museum_id_ac665f54" ON "passes_passvisit" ("museum_id");

CREATE INDEX "passes_passvisit_order_id_bfb249d5" ON "passes_passvisit" ("order_id");

CREATE UNIQUE INDEX "passes_passvisit_order_id_museum_id_a61126d2_uniq" ON "passes_passvisit" ("order_id", "museum_id");

CREATE INDEX "passes_passvisit_scanned_by_id_24ee5f89" ON "passes_passvisit" ("scanned_by_id");

CREATE UNIQUE INDEX "promo_code_unique_ci" ON "promotions_promocode" ((UPPER("code")));

CREATE INDEX "promotions_giftvoucher_issued_by_id_7c73cd35" ON "promotions_giftvoucher" ("issued_by_id");

CREATE INDEX "promotions_promocode_created_by_id_07a1c43c" ON "promotions_promocode" ("created_by_id");

CREATE INDEX "promotions_promocode_museums_museum_id_bc38c25a" ON "promotions_promocode_museums" ("museum_id");

CREATE INDEX "promotions_promocode_museums_promocode_id_cfaba063" ON "promotions_promocode_museums" ("promocode_id");

CREATE UNIQUE INDEX "promotions_promocode_museums_promocode_id_museum_id_277f267a_uniq" ON "promotions_promocode_museums" ("promocode_id", "museum_id");

CREATE INDEX "promotions_promoredemption_booking_id_488b6cba" ON "promotions_promoredemption" ("booking_id");

CREATE INDEX "promotions_promoredemption_code_id_534de749" ON "promotions_promoredemption" ("code_id");

CREATE INDEX "promotions_promoredemption_user_id_792c31a6" ON "promotions_promoredemption" ("user_id");

CREATE INDEX "promotions_voucherredemption_booking_id_a13c170d" ON "promotions_voucherredemption" ("booking_id");

CREATE INDEX "promotions_voucherredemption_voucher_id_20245e98" ON "promotions_voucherredemption" ("voucher_id");

CREATE INDEX "review_place_helpful_idx" ON "museums_review" ("museum_id", "is_published", "helpful_count" DESC, "created_at" DESC);

CREATE INDEX "review_place_published_idx" ON "museums_review" ("museum_id", "is_published", "created_at" DESC);

CREATE INDEX "schools_school_state_id_eaef34aa" ON "schools_school" ("state_id");

CREATE INDEX "schools_school_status_f105f484" ON "schools_school" ("status");

CREATE INDEX "schools_school_verified_by_id_503ac04e" ON "schools_school" ("verified_by_id");

CREATE INDEX "schools_schooltrip_booking_id_fb368938" ON "schools_schooltrip" ("booking_id");

CREATE INDEX "schools_schooltrip_decided_by_id_d87941e6" ON "schools_schooltrip" ("decided_by_id");

CREATE INDEX "schools_schooltrip_museum_id_5873a9c8" ON "schools_schooltrip" ("museum_id");

CREATE INDEX "schools_schooltrip_preferred_date_666a4c36" ON "schools_schooltrip" ("preferred_date");

CREATE INDEX "schools_schooltrip_requested_by_id_804c9aad" ON "schools_schooltrip" ("requested_by_id");

CREATE INDEX "schools_schooltrip_school_id_a9e686fc" ON "schools_schooltrip" ("school_id");

CREATE INDEX "schools_schooltrip_status_9df25933" ON "schools_schooltrip" ("status");

CREATE INDEX "stats_dailystat_museum_id_ef911572" ON "stats_dailystat" ("museum_id");

CREATE INDEX "stats_exportjob_status_7abf1781" ON "stats_exportjob" ("status");

CREATE INDEX "stats_exportjob_user_id_0d79b446" ON "stats_exportjob" ("user_id");

CREATE INDEX "stats_statday_dirty_since_2bb80ca3" ON "stats_statday" ("dirty_since");

CREATE INDEX "support_contactmessage_created_at_d747d043" ON "support_contactmessage" ("created_at");

CREATE INDEX "support_contactmessage_place_slug_6e8416f5" ON "support_contactmessage" ("place_slug");

CREATE INDEX "support_contactmessage_status_e7f7cd12" ON "support_contactmessage" ("status");

CREATE INDEX "support_contactmessage_user_id_94e9100e" ON "support_contactmessage" ("user_id");

CREATE INDEX "trips_favourite_museum_id_5e3c0851" ON "trips_favourite" ("museum_id");

CREATE INDEX "trips_favourite_user_id_abaf9f19" ON "trips_favourite" ("user_id");

CREATE UNIQUE INDEX "trips_favourite_user_id_museum_id_f1e5433b_uniq" ON "trips_favourite" ("user_id", "museum_id");

CREATE INDEX "trips_trip_user_id_b33c249a" ON "trips_trip" ("user_id");

CREATE INDEX "trips_tripstop_museum_id_9fea06eb" ON "trips_tripstop" ("museum_id");

CREATE INDEX "trips_tripstop_trip_id_7360aaaa" ON "trips_tripstop" ("trip_id");

CREATE INDEX "user_joined_idx" ON "accounts_user" ("date_joined" DESC);

CREATE INDEX "user_role_joined_idx" ON "accounts_user" ("role", "date_joined" DESC);

CREATE TRIGGER booking_search_ad AFTER DELETE ON bookings_booking BEGIN DELETE FROM booking_search WHERE rowid = old.id; END;

CREATE TRIGGER booking_search_ai AFTER INSERT ON bookings_booking BEGIN INSERT INTO booking_search (rowid, name, org, place, email, phone, tail) VALUES (new.id, new.visitor_name, new.organisation_name, (SELECT m.name FROM museums_museum m WHERE m.id = new.museum_id), new.visitor_email, substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -10), substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -6) || ' ' || substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -7) || ' ' || substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -8) || ' ' || substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -9)); END;

CREATE TRIGGER booking_search_au AFTER UPDATE ON bookings_booking WHEN old.id IS NOT new.id OR old.visitor_name IS NOT new.visitor_name OR old.organisation_name IS NOT new.organisation_name OR old.visitor_email IS NOT new.visitor_email OR old.visitor_phone IS NOT new.visitor_phone OR old.museum_id IS NOT new.museum_id BEGIN DELETE FROM booking_search WHERE rowid = old.id; INSERT INTO booking_search (rowid, name, org, place, email, phone, tail) VALUES (new.id, new.visitor_name, new.organisation_name, (SELECT m.name FROM museums_museum m WHERE m.id = new.museum_id), new.visitor_email, substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -10), substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -6) || ' ' || substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -7) || ' ' || substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -8) || ' ' || substr(replace(replace(replace(replace(replace(replace(coalesce(new.visitor_phone, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', ''), '.', ''), -9)); END;

CREATE TRIGGER booking_search_place AFTER UPDATE OF name ON museums_museum WHEN old.name IS NOT new.name BEGIN UPDATE booking_search SET place = new.name WHERE rowid IN (SELECT id FROM bookings_booking WHERE museum_id = new.id); END;
