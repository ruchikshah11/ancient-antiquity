import type { Booking } from './types';

/** Promo codes and gift vouchers. */

/** Booking fields added by promo codes / gift vouchers (returned by every booking endpoint). */
export interface BookingCodeFields {
  promo_code: number | null;
  promo_code_text: string | null;
  promo_discount: string;
  voucher_amount: string;
  voucher_code: string | null;
}

export type PromoBooking = Booking & Partial<BookingCodeFields>;

export type DiscountType = 'percent' | 'flat';
export type PromoScope = 'all' | 'museums' | 'place_types';
export type AppliesTo = 'individual' | 'group' | 'both';

export interface PromoCode {
  id: number;
  code: string;
  description: string;
  discount_type: DiscountType;
  value: string;
  max_discount: string | null;
  min_order_amount: string;
  valid_from: string | null;
  valid_to: string | null;
  usage_limit: number | null;
  per_user_limit: number | null;
  scope: PromoScope;
  museums: number[];
  museum_names: string[];
  place_types: string;
  applies_to: AppliesTo;
  first_booking_only: boolean;
  is_active: boolean;
  created_by_email: string | null;
  created_at: string;
  uses_count: number;
  total_discount: string;
}

export interface VoucherRedemption {
  id: number;
  booking_reference: string;
  booking_status: string;
  amount: string;
  created_at: string;
  reversed_at: string | null;
}

export interface GiftVoucher {
  id: number;
  code: string;
  initial_value: string;
  balance: string;
  used_amount: string;
  purchaser_name: string;
  purchaser_email: string;
  recipient_name: string;
  recipient_email: string;
  message: string;
  valid_until: string;
  is_active: boolean;
  is_expired: boolean;
  issued_by_email: string | null;
  created_at: string;
  redemptions: VoucherRedemption[];
}

export const DISCOUNT_TYPES: { value: DiscountType; label: string }[] = [
  { value: 'percent', label: 'Percent (%)' },
  { value: 'flat', label: 'Flat amount (₹)' },
];

export const PROMO_SCOPES: { value: PromoScope; label: string }[] = [
  { value: 'all', label: 'All places' },
  { value: 'museums', label: 'Selected places' },
  { value: 'place_types', label: 'Place types' },
];

export const APPLIES_TO: { value: AppliesTo; label: string }[] = [
  { value: 'both', label: 'Individual and group' },
  { value: 'individual', label: 'Individual bookings only' },
  { value: 'group', label: 'Group bookings only' },
];
