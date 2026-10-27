/** Combo passes, multiple gates and live occupancy. */
import type { GateManifest, ManifestTicket } from './types';

export const PASS_CATEGORIES = ['indian', 'foreign', 'student', 'child'] as const;
export type PassCategory = (typeof PASS_CATEGORIES)[number];
export type PassCounts = Record<PassCategory, number>;

export interface PassSite {
  slug: string;
  name: string;
  place_type: string;
  city_name: string;
  state_name: string;
  image_url: string;
}

export interface ComboPass {
  id: number;
  name: string;
  slug: string;
  description: string;
  image_url: string;
  validity_days: number;
  prices: Record<PassCategory, string>;
  from_price: string;
  featured: boolean;
  sites: PassSite[];
}

/** Admin view of a pass (GET/POST/PATCH /admin/passes/). */
export interface AdminComboPass extends ComboPass {
  price_indian: string;
  price_foreign: string;
  price_student: string;
  price_child: string;
  is_active: boolean;
  orders_count: number;
  created_at: string;
  updated_at: string;
}

export type PassOrderStatus = 'pending' | 'confirmed' | 'cancelled' | 'expired';

export interface PassOrderSite extends PassSite {
  used: boolean;
  visited_at: string | null;
}

export interface PassOrder {
  reference: string;
  status: PassOrderStatus;
  status_label: string;
  pass_name: string;
  pass_slug: string;
  pass_image: string;
  start_date: string;
  end_date: string;
  validity_days: number;
  counts: PassCounts;
  unit_prices: Record<PassCategory, string>;
  total_visitors: number;
  total_amount: string;
  visitor_name: string;
  visitor_email: string;
  visitor_phone: string;
  payment_method: string;
  payment_id: string;
  gateway: string;
  paid_at: string | null;
  created_at: string;
  cancelled_at: string | null;
  hold_expires_at: string | null;
  refund_amount: string;
  refund_status: '' | 'pending' | 'processed' | 'failed';
  refund_status_label: string;
  refundable_amount: string;
  can_cancel: boolean;
  sites: PassOrderSite[];
  user_email: string;
}

/** Response of POST /bookings/checkin/ for an AP- reference. */
export interface PassCheckin {
  kind: 'pass';
  reference: string;
  pass_name: string;
  visitor_name: string;
  total_visitors: number;
  items: { quantity: number; ticket_name: string }[];
  museum_name: string;
  valid_from: string;
  valid_until: string;
  sites_total: number;
  sites_used: number;
}

export interface Gate {
  id: number;
  museum: string;
  museum_name: string;
  name: string;
  is_active: boolean;
  sort_order: number;
}

export interface OccupancySlot {
  slot_id: number;
  start: string;
  end: string;
  capacity: number;
  expected: number;
  entered: number;
  pass_entered: number;
  by_gate: { gate_id: number | null; name: string; entered: number }[];
  booked_pct: number;
  is_current: boolean;
  counted_inside: boolean;
}

export interface OccupancyGate {
  gate_id: number | null;
  name: string;
  is_active: boolean;
  entered: number;
  inside_estimate: number;
}

export interface Occupancy {
  museum: string;
  museum_name: string;
  date: string;
  generated_at: string;
  is_today: boolean;
  totals: {
    expected: number;
    pass_expected: number;
    entered: number;
    entered_pct: number;
    inside_estimate: number | null;
    inside_capacity: number;
    inside_pct: number;
    capacity_today: number;
  };
  estimate_note: string;
  slots: OccupancySlot[];
  gates: OccupancyGate[];
}

export const emptyCounts = (): PassCounts => ({ indian: 0, foreign: 0, student: 0, child: 0 });

/** Pass references start with AP-, booking references with AA-. */
export const isPassReference = (ref: string): boolean => ref.toUpperCase().startsWith('AP-');

/** Gate-manifest extras: the place's open gates, and combo passes valid there today (is_pass). */
export interface GateOption {
  id: number;
  name: string;
}

export interface PassManifestTicket extends ManifestTicket {
  is_pass?: boolean;
  pass_name?: string;
  valid_until?: string;
}

export interface GateManifestWithPasses extends Omit<GateManifest, 'tickets'> {
  tickets: PassManifestTicket[];
  gates?: GateOption[];
}
