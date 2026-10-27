import { api } from './client';

/*
 * Booking-funnel tracking: fire-and-forget, batched, anonymous.
 * A random session id lives in localStorage (no personal data). Staff/admin sessions and kiosks are not tracked
 * (the server ignores them too). Money steps (booking created, paid, cancelled) are derived from bookings on the
 * server, so only page-level steps need tracking calls.
 */

export type FunnelEventName =
  | 'view_place'
  | 'select_slot'
  | 'start_booking'
  | 'view_checkout'
  | 'payment_started'
  | 'paid'
  | 'cancelled';

export interface TrackData {
  /** Place slug. */
  museum?: string;
  /** Booking reference (linked only when it belongs to the signed-in visitor). */
  booking?: string;
}

interface QueuedEvent extends TrackData {
  event: FunnelEventName;
}

const SESSION_KEY = 'aa_funnel_session';
const UTM_KEY = 'aa_funnel_utm';
const USER_KEY = 'aa_user';
const FLUSH_MS = 2000;
const MAX_BATCH = 20;

let queue: QueuedEvent[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;

function storageGet(key: string, session = false): string | null {
  try {
    return (session ? sessionStorage : localStorage).getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string, session = false): void {
  try {
    (session ? sessionStorage : localStorage).setItem(key, value);
  } catch {
    /* storage unavailable: this visit is simply untracked across reloads */
  }
}

function randomId(): string {
  const bytes = new Uint8Array(16);
  if (window.crypto?.getRandomValues) window.crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function sessionId(): string {
  let id = storageGet(SESSION_KEY);
  if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
    id = randomId();
    storageSet(SESSION_KEY, id);
  }
  return id;
}

/** Panel users (staff/admin), agents and kiosks are not visitors: never track them. */
function isExcludedUser(): boolean {
  const raw = storageGet(USER_KEY);
  if (!raw) return false;
  try {
    const u = JSON.parse(raw) as { is_panel_user?: boolean; role?: string };
    return Boolean(u.is_panel_user) || u.role === 'kiosk' || u.role === 'agent';
  } catch {
    return false;
  }
}

/** utm_* from the landing URL, remembered for this browser tab (e.g. recovery emails). */
function utm(): Record<string, string> | undefined {
  const params = new URLSearchParams(window.location.search);
  const source = params.get('utm_source');
  if (source) {
    const value = { source, medium: params.get('utm_medium') ?? '', campaign: params.get('utm_campaign') ?? '' };
    storageSet(UTM_KEY, JSON.stringify(value), true);
    return value;
  }
  const saved = storageGet(UTM_KEY, true);
  if (!saved) return undefined;
  try {
    return JSON.parse(saved) as Record<string, string>;
  } catch {
    return undefined;
  }
}

function flush(useBeacon = false): void {
  clearTimeout(timer);
  timer = undefined;
  if (!queue.length) return;
  const events = queue.slice(0, MAX_BATCH);
  queue = queue.slice(MAX_BATCH);
  const body = { session_id: sessionId(), events, utm: utm() };
  const base = api.defaults.baseURL ?? '/api';
  if (useBeacon && typeof navigator.sendBeacon === 'function') {
    // Page is closing: a beacon survives unload (sent without the auth header, so it is anonymous).
    navigator.sendBeacon(`${base}/analytics/events/`, new Blob([JSON.stringify(body)], { type: 'application/json' }));
  } else {
    api.post('/analytics/events/', body).catch(() => undefined);
  }
  if (queue.length) timer = setTimeout(() => flush(), FLUSH_MS);
}

let listening = false;

function listen(): void {
  if (listening) return;
  listening = true;
  window.addEventListener('pagehide', () => flush(true));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush(true);
  });
}

/** Record a funnel step. Never throws and never blocks the page. */
export function track(event: FunnelEventName, data: TrackData = {}): void {
  try {
    if (isExcludedUser()) return;
    if (/bot|crawl|spider|headless/i.test(navigator.userAgent)) return;
    queue.push({ event, ...data });
    listen();
    if (!timer) timer = setTimeout(() => flush(), FLUSH_MS);
  } catch {
    /* tracking must never break the page */
  }
}

/* ------------------------------------------------------------------ admin funnel report */

export interface FunnelStep {
  key: FunnelEventName;
  label: string;
  count: number;
  source: 'sessions' | 'bookings';
  pct_of_first: number | null;
  pct_of_previous: number | null;
}

export interface FunnelPlace {
  slug: string;
  name: string;
  city: string;
  views: number;
  paid: number;
  conversion: number | null;
}

export interface FunnelDay {
  date: string;
  views: number;
  started: number;
  paid: number;
}

export interface FunnelReport {
  from: string;
  to: string;
  museum: { slug: string; name: string } | null;
  steps: FunnelStep[];
  overall_conversion: number | null;
  cancelled: number;
  abandoned: number;
  top_places: FunnelPlace[];
  recovery: { sent: number; converted: number; conversion: number | null };
  daily: FunnelDay[];
}
