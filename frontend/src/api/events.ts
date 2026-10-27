/** Events & shows (light & sound shows, night viewings, walks...) and the waitlist. */
import { api } from './client';

export const EVENT_KINDS = ['light_sound', 'night_viewing', 'exhibition', 'heritage_walk', 'workshop', 'other'] as const;
export type EventKind = (typeof EVENT_KINDS)[number];

export const KIND_ICONS: Record<EventKind, string> = {
  light_sound: 'bi-lightbulb',
  night_viewing: 'bi-moon-stars',
  exhibition: 'bi-easel',
  heritage_walk: 'bi-signpost-2',
  workshop: 'bi-brush',
  other: 'bi-calendar-event',
};

export interface EventPrice {
  id: number;
  name: string;
  price: string;
  sort: number;
}

/** GET /events/ */
export interface EventSummary {
  id: number;
  slug: string;
  title: string;
  kind: EventKind;
  kind_label: string;
  description: string;
  image_url: string;
  language: string;
  duration_minutes: number;
  featured: boolean;
  museum_slug: string;
  museum_name: string;
  museum_image: string;
  city_name: string;
  state_name: string;
  state_id: number;
  from_price: string | null;
  next_date: string | null;
  upcoming_sessions: number;
}

export interface EventSessionInfo {
  id: number;
  date: string;
  start_time: string;
  end_time: string;
  capacity: number;
  available: number;
  sold_out: boolean;
  closed_reason: string;
}

/** GET /events/<slug>/ */
export interface EventDetail extends EventSummary {
  prices: EventPrice[];
  sessions: EventSessionInfo[];
}

export type WaitlistChannel = 'email' | 'sms' | 'whatsapp' | 'push';
export const WAITLIST_CHANNELS: WaitlistChannel[] = ['email', 'sms', 'whatsapp', 'push'];

export interface WaitlistEntry {
  id: number;
  museum_slug: string;
  museum_name: string;
  slot: number | null;
  event_session: number | null;
  event_title: string;
  event_slug: string | null;
  visit_date: string;
  start_time: string | null;
  end_time: string | null;
  quantity: number;
  status: 'waiting' | 'notified' | 'booked' | 'expired';
  status_label: string;
  notify_channels: WaitlistChannel[];
  created_at: string;
  notified_at: string | null;
}

export interface WaitlistRequest {
  museum?: string;
  slot?: number;
  visit_date?: string;
  event_session?: number;
  quantity: number;
  notify_channels?: WaitlistChannel[];
}

export const joinWaitlist = (body: WaitlistRequest) => api.post<WaitlistEntry>('/waitlist/', body);
export const myWaitlist = () => api.get<WaitlistEntry[]>('/waitlist/');
export const leaveWaitlist = (id: number) => api.delete(`/waitlist/${id}/`);

/* ---- Admin ---- */

export interface AdminEvent {
  id: number;
  museum: string;
  museum_name: string;
  title: string;
  slug: string;
  kind: EventKind;
  kind_label: string;
  description: string;
  image_url: string;
  language: string;
  duration_minutes: number;
  is_active: boolean;
  featured: boolean;
  prices: EventPrice[];
  sessions_count: number;
  upcoming_sessions: number;
}

export interface AdminEventSession {
  id: number;
  event: number;
  date: string;
  start_time: string;
  end_time: string;
  capacity: number;
  is_active: boolean;
  booked: number;
  waiting: number;
}

export interface AdminEventPrice extends EventPrice {
  event: number;
}
