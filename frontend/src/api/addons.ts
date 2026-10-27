/** Ticket add-ons: what a place sells with its tickets, and choosing them for a pending booking. */
import { api } from './client';
import type { Invoice } from './reports';
import type { Booking } from './types';

export type AddOnKind = 'audio_guide' | 'camera' | 'video' | 'guided_tour' | 'parking' | 'wheelchair' | 'locker' | 'other';
export type AddOnPer = 'person' | 'booking';

export const ADDON_KINDS: { value: AddOnKind; label: string; icon: string }[] = [
  { value: 'audio_guide', label: 'Audio guide', icon: 'headphones' },
  { value: 'camera', label: 'Camera permit', icon: 'camera' },
  { value: 'video', label: 'Video camera permit', icon: 'camera-video' },
  { value: 'guided_tour', label: 'Guided tour', icon: 'signpost-2' },
  { value: 'parking', label: 'Parking', icon: 'cone-striped' },
  { value: 'wheelchair', label: 'Wheelchair', icon: 'life-preserver' },
  { value: 'locker', label: 'Locker / cloakroom', icon: 'safe' },
  { value: 'other', label: 'Other', icon: 'plus-circle' },
];

/** Public add-on (GET /museums/<slug>/addons/). */
export interface AddOn {
  id: number;
  name: string;
  description: string;
  kind: AddOnKind;
  kind_label: string;
  icon: string;
  price: string;
  per: AddOnPer;
  per_label: string;
  max_per_booking: number | null;
  daily_stock: number | null;
  /** Units left on the asked date (null: unlimited or no date given). */
  remaining: number | null;
}

/** Admin view (GET/POST/PATCH /admin/addons/). */
export interface AdminAddOn extends AddOn {
  museum: string;
  museum_name: string;
  is_active: boolean;
  sort: number;
  sold_count: number;
  created_at: string;
  updated_at: string;
}

/** Most of an add-on one booking of `visitors` people may take (mirrors AddOn.quantity_limit on the server). */
export function addonLimit(a: AddOn, visitors: number): number {
  const base = a.per === 'person' ? (a.max_per_booking ? Math.min(visitors, a.max_per_booking) : visitors) : a.max_per_booking || 1;
  return a.remaining === null ? base : Math.min(base, a.remaining);
}

export const fetchPlaceAddOns = (slug: string, date?: string, booking?: string): Promise<AddOn[]> =>
  api.get<AddOn[]>(`/museums/${slug}/addons/`, { params: { date, booking } }).then((r) => r.data);

/** Replace the add-ons of a pending booking; returns the re-priced booking. */
export const saveBookingAddOns = (reference: string, items: { addon: number; quantity: number }[]): Promise<Booking> =>
  api.post<Booking>(`/bookings/${reference}/addons/`, { items }).then((r) => r.data);

/** Invoice fields added for add-ons and the Heritage Card (older invoices don't have them). */
export type InvoiceWithExtras = Omit<Invoice, 'items'> & {
  items: (Invoice['items'][number] & { kind?: 'ticket' | 'addon' })[];
  membership_discount?: number;
  membership_card?: string;
};
