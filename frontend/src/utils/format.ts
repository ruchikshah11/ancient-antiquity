import { currentLocale } from '../i18n';
const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const num = new Intl.NumberFormat('en-IN');

export const formatINR = (v: string | number | null | undefined) => inr.format(Number(v ?? 0));
export const formatNumber = (v: number | null | undefined) => num.format(v ?? 0);

export const formatPrice = (v: string | number | null | undefined) =>
  Number(v ?? 0) === 0 ? 'Free' : formatINR(v);

const foreignFormats: Record<string, Intl.NumberFormat> = {};

/** An amount in a foreign currency with 2 decimals, e.g. formatForeign(6, 'USD') -> "$6.00". */
export function formatForeign(amount: number, code: string): string {
  try {
    foreignFormats[code] ??= new Intl.NumberFormat('en-IN', {
      style: 'currency', currency: code, minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
    return foreignFormats[code].format(amount);
  } catch {
    return `${code} ${amount.toFixed(2)}`; // unknown currency code
  }
}

/** "14:30:00" -> "2:30 PM" */
export function formatTime(t: string) {
  const [h, m] = t.split(':').map(Number);
  const suffix = h >= 12 ? 'PM' : 'AM';
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${suffix}`;
}

export function formatDate(d: string, opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' }) {
  // Date-only strings are parsed as local dates to avoid timezone shifts.
  const date = /^\d{4}-\d{2}-\d{2}$/.test(d) ? new Date(`${d}T00:00:00`) : new Date(d);
  return date.toLocaleDateString(currentLocale(), opts);
}

export const formatDateTime = (d: string) =>
  new Date(d).toLocaleString(currentLocale(), { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });

export const PLACE_TYPES = [
  { value: 'museum', label: 'Museum', plural: 'Museums', icon: 'bi-bank' },
  { value: 'fort', label: 'Fort', plural: 'Forts', icon: 'bi-shield-shaded' },
  { value: 'palace', label: 'Palace', plural: 'Palaces', icon: 'bi-gem' },
  { value: 'monument', label: 'Monument', plural: 'Monuments', icon: 'bi-building' },
] as const;

export const placeLabel = (t: string) => PLACE_TYPES.find((p) => p.value === t)?.label ?? 'Museum';

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** Local YYYY-MM-DD, offset by n days. */
export function isoDate(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** JS getDay(): Sun=0; Django weekday(): Mon=0. */
export const djangoWeekday = (iso: string) => (new Date(`${iso}T00:00:00`).getDay() + 6) % 7;

/** Ask Wikimedia for a smaller rendition of a 1280px thumbnail (cards don't need full size). */
export const sizedImage = (url: string, width: 330 | 500 | 960 | 1280) =>
  url.includes('wikimedia.org') ? url.replace(/\/1280px-/, `/${width}px-`) : url;

/** Deterministic blue-to-orange gradient as a placeholder image per museum. */
export function museumGradient(seed: string) {
  let h = 0;
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) % 360;
  const hue = 205 + (h % 30);
  return `linear-gradient(135deg, hsl(${hue} 70% 22%), hsl(${hue + 10} 60% 40%) 70%, hsl(24 90% 50%) 140%)`;
}

/** "City, State", or just the state when the city isn't known (listed places are filed under their state). */
export function placeLocation(city?: string | null, state?: string | null): string {
  if (!city || city === state) return state ?? '';
  return state ? `${city}, ${state}` : city;
}
