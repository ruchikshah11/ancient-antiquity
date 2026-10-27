export type Role = 'visitor' | 'staff' | 'admin' | 'agent' | 'kiosk' | 'partner';

export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  role: Role;
  is_active: boolean;
  is_panel_user: boolean;
  is_admin_role: boolean;
  date_joined: string;
  last_login: string | null;
  booking_count?: number;
  /** Sample-data account (never emailed or texted). */
  is_sample?: boolean;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface State {
  id: number;
  name: string;
  code: string;
  is_union_territory: boolean;
  museum_count: number;
}

export interface City {
  id: number;
  name: string;
  state: number;
  state_name: string;
}

export interface Category {
  id: number;
  name: string;
  slug: string;
}

export interface TicketType {
  id?: number;
  name: string;
  description: string;
  price: string;
  sort_order: number;
  is_active: boolean;
}

export interface TimeSlot {
  id?: number;
  start_time: string;
  end_time: string;
  capacity: number;
  is_active: boolean;
}

export type PlaceType = 'museum' | 'fort' | 'palace' | 'monument';

export interface MuseumSummary {
  id: number;
  allow_groups?: boolean;
  allow_individual?: boolean;
  name: string;
  slug: string;
  place_type: PlaceType;
  tagline: string;
  image_url: string;
  /** 'google' when image_url is a Google Maps photo (must be credited to Google Maps). */
  photo_source?: 'google';
  city_name: string;
  state_name: string;
  category_name: string | null;
  opening_time: string;
  closing_time: string;
  closed_weekday: number | null;
  is_featured: boolean;
  is_active: boolean;
  starting_price: string | null;
  avg_rating: number | null;
  review_count: number;
  /** Timings & prices confirmed with the place (admin data verification). */
  info_verified?: boolean;
  info_verified_at?: string | null;
  info_verified_by_name?: string | null;
}

export interface MuseumImage {
  id: number;
  url: string;
  caption: string;
  credit: string;
  source_url: string;
}

export interface Museum extends MuseumSummary {
  image_credit: string;
  image_source_url: string;
  source_url: string;
  images: MuseumImage[];
  city: number;
  state: number;
  category: number | null;
  description: string;
  highlights: string;
  address: string;
  latitude: string | null;
  longitude: string | null;
  established_year: number | null;
  managed_by: string;
  contact_phone: string;
  contact_email: string;
  ticket_types: TicketType[];
  slots: TimeSlot[];
  allow_groups: boolean;
  /** Raw place switch (Admin -> Places); the *_open flags below also include the site-wide switches. */
  allow_individual?: boolean;
  individual_open?: boolean;
  groups_open?: boolean;
  group_requests_open?: boolean;
  school_trips_open?: boolean;
  /** Why online booking is limited here (empty when everything is open). */
  groups_paused_message?: string;
  group_discount_percent: number;
  school_discount_percent: number;
  group_policy: GroupPolicy;
  /** Virtual tour link (360 tour, video or Google Street View) and its kind; '' when none. */
  virtual_tour_url?: string;
  virtual_tour_kind?: VirtualTourKind | '';
}

export type VirtualTourKind = '360' | 'video' | 'google_street_view' | 'other';

/** Site-wide group rules returned with each place. */
export interface GroupPolicy {
  min_size: number;
  max_size: number;
  escorts_per: number;
  slot_share_percent: number;
}

export type GroupType = 'school' | 'college' | 'tour_operator' | 'corporate' | 'ngo' | 'other';

export const GROUP_TYPES: { value: GroupType; label: string; educational: boolean }[] = [
  { value: 'school', label: 'School', educational: true },
  { value: 'college', label: 'College / university', educational: true },
  { value: 'tour_operator', label: 'Tour operator', educational: false },
  { value: 'corporate', label: 'Company / corporate', educational: false },
  { value: 'ngo', label: 'NGO / community group', educational: false },
  { value: 'other', label: 'Other group', educational: false },
];

export interface SlotAvailability {
  id: number;
  start_time: string;
  end_time: string;
  capacity: number;
  booked: number;
  available: number;
  group_available: number;
  bookable: boolean;
}

export interface Availability {
  date: string;
  closed: boolean;
  bookable: boolean;
  slots: SlotAvailability[];
}

export interface Review {
  id: number;
  rating: number;
  title: string;
  comment: string;
  user_name: string;
  /** Approved photos; on your own review also the ones waiting for approval. Admins see all. */
  photos?: ReviewPhoto[];
  /** Visitors who marked this review helpful. */
  helpful_count?: number;
  /** Whether the signed-in visitor marked it helpful. */
  voted_by_me?: boolean;
  created_at: string;
  updated_at: string;
}

/** Answer of POST/DELETE /museums/<slug>/reviews/<id>/helpful/. */
export interface ReviewHelpfulVote {
  id: number;
  helpful_count: number;
  voted_by_me: boolean;
}

export type ReviewPhotoStatus = 'pending' | 'approved' | 'rejected';

export interface ReviewPhoto {
  id: number;
  url: string;
  status: ReviewPhotoStatus;
  status_label: string;
  created_at: string;
}

/** An approved photo in the place's "Visitor photos" strip. */
export interface VisitorPhoto extends ReviewPhoto {
  review_id: number;
  user_name: string;
  rating: number;
}

export interface ReviewSummary {
  average: number | null;
  count: number;
  breakdown: Record<'5' | '4' | '3' | '2' | '1', number>;
  can_review: boolean;
  my_review: Review | null;
  /** One page of other visitors' reviews (your own is in my_review). */
  results: Review[];
  results_total?: number;
  next_offset?: number | null;
  visitor_photos?: VisitorPhoto[];
  photo_limits?: { max_per_review: number; max_mb: number };
}

export interface AdminReview extends Review {
  is_published: boolean;
  museum_name: string;
  museum_slug: string;
  user_email: string;
}

export type BookingStatus = 'pending' | 'confirmed' | 'checked_in' | 'cancelled' | 'expired';

export interface Booking {
  reference: string;
  status: BookingStatus;
  status_label: string;
  museum_name: string;
  museum_slug: string;
  museum_address: string;
  museum_image: string;
  city_name: string;
  state_name: string;
  visit_date: string;
  slot_start: string;
  slot_end: string;
  total_visitors: number;
  total_amount: string;
  items: { ticket_name: string; quantity: number; unit_price: string; line_total: string }[];
  visitor_name: string;
  visitor_email: string;
  visitor_phone: string;
  payment_method: string;
  payment_id: string;
  created_at: string;
  paid_at: string | null;
  cancelled_at: string | null;
  checked_in_at: string | null;
  hold_expires_at: string | null;
  can_cancel: boolean;
  user_email: string;
  channel: 'online' | 'counter' | 'agent' | 'kiosk';
  sold_by_email: string | null;
  is_group: boolean;
  group_type: GroupType | '';
  group_type_label: string;
  organisation_name: string;
  escort_count: number;
  subtotal_amount: string;
  discount_amount: string;
  visitors_arrived: number;
  remaining_to_enter: number;
  gateway: string;
  refund_amount: string;
  refund_status: '' | 'pending' | 'processed' | 'failed';
  refund_status_label: string;
  refund_id: string;
  refundable_amount: string;
  /** Approved large-group bookings hold their seats until this time (instead of the short hold). */
  pay_by: string | null;
  /** Id of the large-group request this booking was created from. */
  group_request: number | null;
  /** Add-ons chosen at checkout (audio guide, camera permit...), priced into total_amount. */
  addons?: BookingAddOnLine[];
  addons_amount?: string;
  /** "2 x Audio guide, 1 x Camera permit" (empty when none). */
  addons_summary?: string;
  /** Heritage Card discount on the entry tickets, and the card it came from. */
  membership_discount?: string;
  membership_card?: string | null;
}

/** One add-on line of a booking (name and price as they were when chosen). */
export interface BookingAddOnLine {
  addon: number;
  name: string;
  kind: string;
  /** Bootstrap icon name without the bi- prefix. */
  icon: string;
  quantity: number;
  unit_price: string;
  line_total: string;
}

/** Check-in reply for a group ticket scanned without a head count. */
export interface NeedsCount {
  needs_count: true;
  booking: Booking;
}

export interface ManifestTicket {
  reference: string;
  status: 'confirmed' | 'checked_in';
  visitor_name: string;
  total_visitors: number;
  slot_start: string;
  slot_end: string;
  items: string;
  checked_in_at: string | null;
  is_group: boolean;
  organisation_name: string;
  visitors_arrived: number;
}

export interface GateManifest {
  museum: string;
  museum_name: string;
  date: string;
  generated_at: string;
  tickets: ManifestTicket[];
}

export interface ImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: { row: number; name?: string; error: string }[];
}

export interface Dashboard {
  totals: {
    revenue: number;
    visitors: number;
    bookings: number;
    expected_today: number;
    checked_in_today: number;
    museums: number;
    users: number;
    group_bookings: number;
    group_visitors: number;
  };
  daily: { date: string; bookings: number; revenue: number }[];
  top_museums: { name: string; slug: string; revenue: number; visitors: number }[];
  by_state: { state: string; visitors: number; revenue: number }[];
  status_counts: Partial<Record<BookingStatus, number>>;
  by_channel: Partial<Record<'online' | 'counter', { bookings: number; revenue: number; visitors: number }>>;
  recent: Booking[];
}

// ---------- School trips ----------

export type SchoolBoard = 'cbse' | 'icse' | 'state' | 'ib' | 'other';
export type SchoolStatus = 'pending' | 'verified' | 'rejected';
export type SchoolTripStatus = 'submitted' | 'approved' | 'declined' | 'cancelled' | 'completed';
export type SlotPreference = 'morning' | 'afternoon';
export type GuideLanguage = '' | 'hi' | 'en';

export interface School {
  id: number;
  name: string;
  board: SchoolBoard;
  board_label: string;
  udise_code: string;
  address: string;
  city: string;
  state: number;
  state_name: string;
  principal_name: string;
  phone: string;
  contact_name: string;
  contact_phone: string;
  contact_email: string;
  status: SchoolStatus;
  status_label: string;
  rejection_reason: string;
  verified_by_email: string | null;
  verified_at: string | null;
  owner_email: string;
  trip_count: number;
  created_at: string;
  updated_at: string;
}

export interface SchoolInput {
  name: string;
  board: SchoolBoard;
  udise_code: string;
  address: string;
  city: string;
  state: number;
  principal_name: string;
  phone: string;
  contact_name: string;
  contact_phone: string;
  contact_email: string;
}

export interface SchoolTrip {
  id: number;
  reference: string;
  school: number;
  school_name: string;
  school_city: string;
  school_board: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  museum_name: string;
  museum_slug: string;
  city_name: string;
  preferred_date: string;
  alternative_date: string | null;
  slot_preference: SlotPreference;
  slot_preference_label: string;
  grades: string;
  students: number;
  young_students: number;
  teachers: number;
  helpers: number;
  free_teachers: number;
  accessibility_needs: string;
  guide_language: GuideLanguage;
  guide_language_label: string;
  notes: string;
  status: SchoolTripStatus;
  status_label: string;
  estimated_amount: string;
  quoted_amount: string | null;
  staff_note: string;
  approved_date: string | null;
  booking: Booking | null;
  decided_by_email: string | null;
  decided_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  can_cancel: boolean;
  can_pay: boolean;
}

export interface SchoolTripInput {
  museum: string;
  preferred_date: string;
  alternative_date: string | null;
  slot_preference: SlotPreference;
  grades: string;
  students: number;
  young_students: number;
  teachers: number;
  helpers: number;
  accessibility_needs: string;
  guide_language: GuideLanguage;
  notes: string;
}

export interface SchoolTicketRef {
  id: number;
  name: string;
  price: string;
}

export interface SchoolEstimateLine {
  kind: 'student' | 'child' | 'adult';
  name: string;
  quantity: number;
  unit_price: string;
  amount: string;
}

export interface SchoolEstimate {
  lines: SchoolEstimateLine[];
  students: number;
  young_students: number;
  teachers: number;
  helpers: number;
  free_teachers: number;
  teachers_needed: number;
  people: number;
  subtotal: string;
  discount_percent: number;
  discount: string;
  total: string;
  student_ticket: SchoolTicketRef | null;
  child_ticket: SchoolTicketRef | null;
  adult_ticket: SchoolTicketRef | null;
  date: string;
  date_error?: string | null;
}

export interface SchoolSlotRoom {
  slot_id: number;
  start: string;
  end: string;
  capacity: number;
  free: number;
  group_room: number;
  closed: boolean;
}

export interface SchoolTripSlots {
  date: string;
  people: number;
  date_error: string | null;
  slots: SchoolSlotRoom[];
}

// --- Pricing insights (GET /admin/pricing-suggestions/) ---------------------------------------------

export type PricingCellStatus = 'busy' | 'quiet' | 'normal' | 'nodata' | 'closed';

export interface PricingCell {
  slot: number;
  /** Open days of this weekday x slot in the period. */
  days: number;
  visitors: number;
  /** Average share of capacity used (0..1+), null when the slot was never open. */
  fill: number | null;
  busy_days: number;
  quiet_days: number;
  status: PricingCellStatus;
  /** Signed percent (+15 premium, -20 discount, 0 none). */
  suggested_percent: number;
}

export interface PricingRulePayload {
  museum: string;
  name: string;
  weekdays: string;
  adjustment_type: 'percent';
  value: string;
  start_date: string;
  end_date: string;
  priority: number;
  is_active: boolean;
}

export interface PricingSuggestion {
  kind: 'premium' | 'discount';
  weekday: number;
  weekday_label: string;
  percent: number;
  slots: { slot: number; fill: number | null; suggested_percent: number }[];
  all_slots: boolean;
  conflict: boolean;
  visitors_per_week: { current: number; estimated: number };
  revenue_per_week: { current: number; estimated: number; change: number };
  revenue_change_over_period: number;
  rule: PricingRulePayload;
}

export interface PricingInsights {
  museum: { slug: string; name: string };
  weeks: number;
  from: string;
  to: string;
  elasticity: number;
  thresholds: {
    busy_fill: number;
    quiet_fill: number;
    consistent_share: number;
    min_days: number;
    premium_percent: [number, number];
    discount_percent: [number, number];
  };
  assumption: string;
  average_ticket_revenue_per_visitor: number;
  slots: { id: number; start_time: string; end_time: string; capacity: number }[];
  grid: { weekday: number; label: string; cells: PricingCell[] }[];
  suggestions: PricingSuggestion[];
  can_create_rules: boolean;
}

// --- Partner portal (/partner/...) -------------------------------------------------------------------

export interface PartnerPlace {
  slug: string;
  name: string;
  city_name: string;
  state_name: string;
  place_type: string;
  image_url: string;
}

export interface PartnerMe {
  email: string;
  places: PartnerPlace[];
}

export interface PartnerFigures {
  visitors: number;
  bookings: number;
  revenue: string;
  refunds: string;
}

export type PartnerPeriod = 'today' | 'this_month' | 'last_month';

export interface PartnerOverview {
  date: string;
  periods: Record<PartnerPeriod, { from: string; to: string }>;
  places: ({ slug: string; name: string; city_name: string; place_type: string } & Record<PartnerPeriod, PartnerFigures>)[];
  totals: Record<PartnerPeriod, PartnerFigures>;
}

export interface PartnerTrendDay {
  date: string;
  visitors: number;
  revenue: string;
}

export interface PartnerTrend {
  days: number;
  daily: PartnerTrendDay[];
}

export interface PartnerReview {
  id: number;
  museum_slug: string;
  museum_name: string;
  rating: number;
  title: string;
  comment: string;
  user_name: string;
  helpful_count: number;
  created_at: string;
}

export interface PartnerReviews {
  count: number;
  next_offset: number | null;
  results: PartnerReview[];
}

export interface PartnerSettlement {
  id: number;
  museum_name: string;
  museum_slug: string;
  city_name: string;
  period_start: string;
  period_end: string;
  booking_count: number;
  visitor_count: number;
  gross_total: string;
  refunds: string;
  platform_fee: string;
  gst_on_fee: string;
  net_payable: string;
  status: 'approved' | 'paid';
  status_label: string;
  approved_at: string | null;
  paid_reference: string;
  paid_at: string | null;
  payout_account: { bank_name: string; account_number: string } | null;
}
