/** Donations (80G receipts) and approximate foreign-currency rates for price hints. */
import { api } from './client';
import type { Paginated } from './types';

export type DonationStatus = 'pending' | 'paid' | 'failed' | 'refunded';

export interface TrustInfo {
  name: string;
  pan: string;
  registration_80g: string;
}

export interface DonationInfo {
  trust: TrustInfo;
  min_amount: string;
  presets: number[];
  provider: 'razorpay' | 'mock';
}

export interface Donation {
  reference: string;
  status: DonationStatus;
  status_label: string;
  amount: string;
  amount_in_words: string;
  museum_slug: string | null;
  museum_name: string | null;
  purpose: string;
  donor_name: string;
  donor_email: string;
  donor_phone: string;
  donor_pan: string;
  donor_address: string;
  wants_80g: boolean;
  is_80g_eligible: boolean;
  receipt_number: string | null;
  payment_method: string;
  payment_id: string;
  gateway: string;
  created_at: string;
  paid_at: string | null;
  refunded_at: string | null;
  trust: TrustInfo;
  /** Signed token that opens this donation without signing in (kept in the receipt link). */
  access_token: string;
}

export interface DonationInput {
  amount: number;
  museum?: string | null;
  donor_name: string;
  donor_email: string;
  donor_phone: string;
  donor_pan: string;
  donor_address: string;
  wants_80g: boolean;
}

export interface AdminDonation extends Omit<Donation, 'trust' | 'access_token'> {
  user_email: string | null;
  gateway_order_id: string;
  refund_id: string;
}

export interface DonationTotals {
  count: number;
  paid_count: number;
  paid_amount: string;
  paid_80g_amount: string;
  refunded_amount: string;
}

export interface AdminDonationPage extends Paginated<AdminDonation> {
  totals: DonationTotals;
}

export interface AdminDonationFilters {
  status?: string;
  museum?: string; // place slug, or "general"
  date_from?: string;
  date_to?: string;
  wants_80g?: '' | 'true' | 'false';
  search?: string;
  page?: number;
}

export const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

/** Path of the receipt page; the token lets guests open it. */
export const receiptPath = (d: Pick<Donation, 'reference' | 'access_token'>): string =>
  `/donations/${d.reference}?token=${encodeURIComponent(d.access_token)}`;

const clean = (filters: AdminDonationFilters): Record<string, string | number> =>
  Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== '' && v !== undefined && v !== null)) as Record<string, string | number>;

export const adminDonationParams = clean;

/** Admin: the Form 10BD CSV, saved as a file. */
export async function downloadDonationsCsv(filters: AdminDonationFilters): Promise<void> {
  const { page: _page, ...rest } = filters;
  const res = await api.get<Blob>('/admin/donations/export/', { params: clean(rest), responseType: 'blob' });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  const match = /filename="([^"]+)"/.exec(String(res.headers['content-disposition'] ?? ''));
  a.href = url;
  a.download = match?.[1] ?? 'donations-10BD.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------- foreign-currency hints

export interface FxRates {
  base: 'INR';
  /** 1 INR = rates[code] units of that currency. */
  rates: Record<string, number>;
  updated: string;
}

/** Currencies offered in the picker (shown only when the server has a rate for them). */
export const FOREIGN_CURRENCIES = ['USD', 'EUR', 'GBP', 'AED'] as const;

const CURRENCY_KEY = 'aa_currency';
const CURRENCY_EVENT = 'aa-currency-change';

let ratesPromise: Promise<FxRates | null> | null = null;

/** Fetched once per page load and shared by every hint on the page. */
export function loadFxRates(): Promise<FxRates | null> {
  ratesPromise ??= api
    .get<FxRates>('/fx-rates/')
    .then((r) => r.data)
    .catch(() => {
      ratesPromise = null; // try again on the next hint
      return null;
    });
  return ratesPromise;
}

/** The visitor's chosen display currency: 'INR' (no hints) or a foreign code. */
export function getCurrency(): string {
  try {
    return localStorage.getItem(CURRENCY_KEY) || 'INR';
  } catch {
    return 'INR';
  }
}

export function setCurrency(code: string): void {
  try {
    if (code === 'INR') localStorage.removeItem(CURRENCY_KEY);
    else localStorage.setItem(CURRENCY_KEY, code);
  } catch {
    /* storage unavailable: still applies to this page */
  }
  window.dispatchEvent(new CustomEvent(CURRENCY_EVENT, { detail: code }));
}

/** Calls `fn` when the currency changes (this tab or another one). Returns an unsubscribe function. */
export function onCurrencyChange(fn: () => void): () => void {
  const onStorage = (e: StorageEvent): void => {
    if (e.key === CURRENCY_KEY) fn();
  };
  window.addEventListener(CURRENCY_EVENT, fn);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(CURRENCY_EVENT, fn);
    window.removeEventListener('storage', onStorage);
  };
}
