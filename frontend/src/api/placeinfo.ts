import type { Availability, Museum, SlotAvailability } from './types';

/* Closures calendar, seasonal / peak pricing, facilities and live crowd level. */

export type CrowdLevel = 'quiet' | 'moderate' | 'busy' | 'full';

export interface SlotAvailabilityInfo extends SlotAvailability {
  /** Partial closure of this slot on the chosen date (null when open). */
  closed_reason?: string | null;
  crowd?: CrowdLevel;
  /** Only for today: people already through the gate in this slot. */
  entered_so_far?: number;
}

export interface TicketPrice {
  ticket_type: number;
  name: string;
  base_price: string;
  price: string;
  /** Name of the seasonal / peak rule that set the price (null = normal price). */
  rule: string | null;
}

export interface AvailabilityInfo extends Availability {
  /** Calendar closure reason when the whole day is closed (null for the weekly closed day). */
  closure_reason?: string | null;
  slots: SlotAvailabilityInfo[];
  prices?: TicketPrice[];
}

export interface ClosureSlot {
  id: number;
  start_time: string;
  end_time: string;
}

/** GET /museums/<slug>/closures/ */
export interface PublicClosure {
  id: number;
  start_date: string;
  end_date: string;
  reason: string;
  all_day: boolean;
  slots: ClosureSlot[];
  all_places: boolean;
}

/** /admin/closures/ */
export interface AdminClosure extends PublicClosure {
  museum: string | null;
  museum_name: string | null;
  created_by_email: string | null;
  created_at: string;
}

export interface ClosureInput {
  museum: string | null;
  start_date: string;
  end_date: string;
  reason: string;
  all_day: boolean;
  slot_ids: number[];
}

export type AdjustmentType = 'percent' | 'fixed_price';

/** /admin/price-rules/ */
export interface PriceRule {
  id?: number;
  museum: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
  /** Comma separated 0-6 (Monday = 0); empty = every day. */
  weekdays: string;
  ticket_type: number | null;
  ticket_type_name?: string | null;
  adjustment_type: AdjustmentType;
  value: string;
  priority: number;
  is_active: boolean;
}

export type Photography = 'allowed' | 'no_flash' | 'not_allowed' | 'paid';

export interface Facilities {
  wheelchair?: boolean;
  lift?: boolean;
  toilets?: boolean;
  accessible_toilet?: boolean;
  drinking_water?: boolean;
  cloakroom?: boolean;
  parking?: boolean;
  cafeteria?: boolean;
  wifi?: boolean;
  guide_available?: boolean;
  audio_guide?: boolean;
  baby_care?: boolean;
  photography?: Photography;
  camera_fee_note?: string;
  nearest_metro?: string;
  nearest_station?: string;
  best_time_to_visit?: string;
  avg_visit_minutes?: number;
  dress_code?: string;
  notes?: string;
}

export type FacilityFlag =
  | 'wheelchair' | 'lift' | 'toilets' | 'accessible_toilet' | 'drinking_water' | 'cloakroom' | 'parking'
  | 'cafeteria' | 'wifi' | 'guide_available' | 'audio_guide' | 'baby_care';

export type FacilityText = 'camera_fee_note' | 'nearest_metro' | 'nearest_station' | 'best_time_to_visit' | 'dress_code' | 'notes';

/** Switches with their admin label and Bootstrap Icons 1.5.0 icon. */
export const FACILITY_FLAGS: { key: FacilityFlag; label: string; icon: string }[] = [
  { key: 'wheelchair', label: 'Wheelchair access', icon: 'bi-person-check' },
  { key: 'lift', label: 'Lift', icon: 'bi-arrow-down-up' },
  { key: 'toilets', label: 'Toilets', icon: 'bi-door-closed' },
  { key: 'accessible_toilet', label: 'Accessible toilet', icon: 'bi-door-open' },
  { key: 'drinking_water', label: 'Drinking water', icon: 'bi-droplet' },
  { key: 'cloakroom', label: 'Cloakroom', icon: 'bi-handbag' },
  { key: 'parking', label: 'Parking', icon: 'bi-signpost' },
  { key: 'cafeteria', label: 'Cafeteria', icon: 'bi-cup-straw' },
  { key: 'wifi', label: 'Wi-Fi', icon: 'bi-wifi' },
  { key: 'guide_available', label: 'Guides available', icon: 'bi-person-badge' },
  { key: 'audio_guide', label: 'Audio guide', icon: 'bi-headphones' },
  { key: 'baby_care', label: 'Baby care room', icon: 'bi-heart' },
];

export const FACILITY_TEXTS: { key: FacilityText; label: string; icon: string }[] = [
  { key: 'nearest_metro', label: 'Nearest metro', icon: 'bi-geo-alt' },
  { key: 'nearest_station', label: 'Nearest railway station', icon: 'bi-signpost-split' },
  { key: 'best_time_to_visit', label: 'Best time to visit', icon: 'bi-sun' },
  { key: 'dress_code', label: 'Dress code', icon: 'bi-person' },
  { key: 'camera_fee_note', label: 'Camera fee note', icon: 'bi-cash' },
  { key: 'notes', label: 'Other notes', icon: 'bi-info-circle' },
];

export const PHOTOGRAPHY: { value: Photography; label: string }[] = [
  { value: 'allowed', label: 'Allowed' },
  { value: 'no_flash', label: 'Allowed without flash' },
  { value: 'paid', label: 'Allowed with a camera ticket' },
  { value: 'not_allowed', label: 'Not allowed' },
];

export type MuseumWithInfo = Museum & { facilities?: Facilities };

/** Bootstrap background class for the crowd dot (always shown next to a text label). */
export const CROWD_DOT: Record<CrowdLevel, string> = {
  quiet: 'bg-success',
  moderate: 'bg-warning',
  busy: 'bg-danger',
  full: 'bg-dark',
};
