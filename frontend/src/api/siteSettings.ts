import { cachedGet } from './cache';

/** Site-wide booking switches (Admin -> Settings). */
export interface SiteSettings {
  individual_bookings_enabled: boolean;
  group_bookings_enabled: boolean;
  group_requests_enabled: boolean;
  school_trips_enabled: boolean;
  events_enabled: boolean;
  passes_enabled: boolean;
  paused_message: string;
  /** Footer overrides (empty = standard translated wording). {year} in the copyright = current year. */
  footer_brand?: string;
  footer_tagline?: string;
  footer_copyright?: string;
}

export interface AdminSiteSettings extends SiteSettings {
  updated_at: string | null;
  updated_by_name: string | null;
}

/** Calls onData with cached, then fresh, settings. */
export const loadSiteSettings = (onData: (s: SiteSettings) => void): Promise<unknown> =>
  cachedGet<SiteSettings>('/site-settings/', undefined, onData);
