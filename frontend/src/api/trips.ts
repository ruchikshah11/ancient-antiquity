import { api } from './client';
import type { MuseumSummary, PlaceType } from './types';

/** Compact place for the map (GET /places/geo/). `approximate`: pinned at its city's centre. */
export interface GeoPlace {
  id: number;
  slug: string;
  name: string;
  place_type: PlaceType;
  city: string;
  state: string;
  lat: number;
  lng: number;
  approximate: boolean;
  image_url: string;
  starting_price: string | null;
  distance_km?: number;
}

export interface NearbyResponse {
  count: number;
  radius_km: number;
  results: GeoPlace[];
}

export interface FavouriteItem {
  created_at: string;
  museum: MuseumSummary;
}

export interface StopPlace {
  id: number;
  slug: string;
  name: string;
  place_type: PlaceType;
  city_name: string;
  state_name: string;
  image_url: string;
  opening_time: string;
  closing_time: string;
  closed_weekday: number | null;
  starting_price: string | null;
  is_active: boolean;
  lat: number | null;
  lng: number | null;
  approximate: boolean | null;
}

export interface TripStop {
  id: number;
  place: StopPlace;
  day: number;
  order: number;
  planned_time: string | null;
  notes: string;
}

export interface TripSummary {
  id: number;
  title: string;
  start_date: string | null;
  end_date: string | null;
  notes: string;
  day_count: number | null;
  stop_count: number;
  created_at: string;
  updated_at: string;
}

export interface Trip extends TripSummary {
  stops: TripStop[];
}

export interface TripInput {
  title: string;
  start_date: string | null;
  end_date: string | null;
  notes?: string;
}

export const MAX_TRIP_DAYS = 60;

/** Great-circle distance in km. */
export function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const rad = (d: number): number => (d * Math.PI) / 180;
  const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
  return 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** "850 m" / "12 km" / "1,240 km" */
export function formatKm(km: number): string {
  if (km < 1) return `${Math.max(50, Math.round((km * 1000) / 50) * 50)} m`;
  return `${(km < 10 ? Math.round(km * 10) / 10 : Math.round(km)).toLocaleString('en-IN')} km`;
}

export type GeoErrorKind = 'unsupported' | 'denied' | 'unavailable' | 'timeout';

/** navigator.geolocation as a promise; rejects with a GeoErrorKind. */
export function currentPosition(): Promise<{ lat: number; lng: number }> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject('unsupported' as GeoErrorKind);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      (err) => reject((err.code === 1 ? 'denied' : err.code === 3 ? 'timeout' : 'unavailable') as GeoErrorKind),
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 5 * 60 * 1000 },
    );
  });
}

export const geoErrorKind = (err: unknown): GeoErrorKind =>
  err === 'unsupported' || err === 'denied' || err === 'timeout' ? err : 'unavailable';

export const nearby = (lat: number, lng: number, opts: { radius_km?: number; type?: string; limit?: number } = {}) =>
  api.get<NearbyResponse>('/places/nearby/', { params: { lat: lat.toFixed(5), lng: lng.toFixed(5), ...opts } }).then((r) => r.data);

/*
 * Favourite slugs, shared by every heart on the page: one /favourites/ids/ request, then kept in memory.
 * Listeners re-render hearts when another card (or the favourites page) changes the set.
 */
export class FavouriteStore {
  private static slugs: Set<string> | null = null;
  /** True once the server list for the current user has arrived. */
  public static loaded = false;
  private static userKey: string | null = null;
  private static loading: Promise<Set<string>> | null = null;
  private static listeners = new Set<() => void>();

  public static subscribe(fn: () => void): () => void {
    FavouriteStore.listeners.add(fn);
    return () => FavouriteStore.listeners.delete(fn);
  }

  private static emit(): void {
    FavouriteStore.listeners.forEach((fn) => fn());
  }

  public static has(slug: string): boolean {
    return FavouriteStore.slugs?.has(slug) ?? false;
  }

  /** Load once per signed-in user; `userKey` changes on login/logout. */
  public static load(userKey: string | null): Promise<Set<string>> {
    if (userKey !== FavouriteStore.userKey) {
      FavouriteStore.userKey = userKey;
      FavouriteStore.slugs = null;
      FavouriteStore.loading = null;
      FavouriteStore.loaded = false;
    }
    if (!userKey) {
      FavouriteStore.slugs = new Set();
      return Promise.resolve(FavouriteStore.slugs);
    }
    if (FavouriteStore.slugs) return Promise.resolve(FavouriteStore.slugs);
    FavouriteStore.loading ??= api
      .get<string[]>('/favourites/ids/')
      .then((r) => {
        if (FavouriteStore.userKey === userKey) {
          FavouriteStore.slugs = new Set([...r.data, ...(FavouriteStore.slugs ?? [])]);
          FavouriteStore.loaded = true;
          FavouriteStore.emit();
        }
        return new Set(r.data);
      })
      .catch(() => {
        FavouriteStore.loading = null;
        return new Set<string>();
      });
    return FavouriteStore.loading;
  }

  public static async set(slug: string, on: boolean): Promise<void> {
    const slugs = (FavouriteStore.slugs ??= new Set());
    if (on) slugs.add(slug);
    else slugs.delete(slug);
    FavouriteStore.emit(); // optimistic
    try {
      if (on) await api.post('/favourites/', { museum: slug });
      else await api.delete(`/favourites/${encodeURIComponent(slug)}/`);
    } catch (err) {
      if (on) slugs.delete(slug);
      else slugs.add(slug);
      FavouriteStore.emit();
      throw err;
    }
  }
}

export const tripsApi = {
  list: () => api.get<TripSummary[]>('/trips/').then((r) => r.data),
  get: (id: number | string) => api.get<Trip>(`/trips/${id}/`).then((r) => r.data),
  create: (data: TripInput) => api.post<Trip>('/trips/', data).then((r) => r.data),
  update: (id: number, data: Partial<TripInput>) => api.patch<Trip>(`/trips/${id}/`, data).then((r) => r.data),
  remove: (id: number) => api.delete(`/trips/${id}/`),
  addStop: (id: number, museum: string, day = 1) => api.post<TripStop>(`/trips/${id}/stops/`, { museum, day }).then((r) => r.data),
  updateStop: (id: number, stopId: number, data: Partial<{ day: number; planned_time: string | null; notes: string }>) =>
    api.patch<TripStop>(`/trips/${id}/stops/${stopId}/`, data).then((r) => r.data),
  removeStop: (id: number, stopId: number) => api.delete(`/trips/${id}/stops/${stopId}/`),
  reorder: (id: number, day: number, stopIds: number[]) =>
    api.post<Trip>(`/trips/${id}/reorder/`, { day, stop_ids: stopIds }).then((r) => r.data),
};
