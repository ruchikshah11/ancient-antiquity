import { api } from './client';

/*
 * IndexedDB response cache for public, read-only API data (places, states, categories, cities).
 * Stale-while-revalidate: the saved copy renders immediately, the network copy replaces it when it arrives.
 * Never use this for personal or fast-changing data (bookings, availability, reviews, auth).
 */

const DB_NAME = 'ancient-antiquity';
const DB_VERSION = 1;
const STORE = 'api';
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // older entries are ignored and pruned
const CACHE_VERSION = 4; // bump when API response shapes change

type Entry = { key: string; data: unknown; savedAt: number; v: number };
type Params = Record<string, string | number | boolean | undefined>;

let dbPromise: Promise<IDBDatabase | null> | null = null;

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      if (typeof indexedDB === 'undefined') return resolve(null);
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: 'key' }).createIndex('savedAt', 'savedAt');
      };
      req.onsuccess = () => {
        resolve(req.result);
        prune(req.result);
      };
      req.onerror = () => resolve(null); // private mode / blocked storage: just skip caching
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

function tx<T>(db: IDBDatabase, mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T | undefined> {
  return new Promise((resolve) => {
    try {
      const req = run(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(undefined);
    } catch {
      resolve(undefined);
    }
  });
}

function prune(db: IDBDatabase) {
  try {
    const range = IDBKeyRange.upperBound(Date.now() - MAX_AGE_MS);
    const cursorReq = db.transaction(STORE, 'readwrite').objectStore(STORE).index('savedAt').openCursor(range);
    cursorReq.onsuccess = () => {
      const cursor = cursorReq.result;
      if (cursor) {
        cursor.delete();
        cursor.continue();
      }
    };
  } catch {
    /* ignore */
  }
}

export function cacheKey(url: string, params?: Params) {
  const qs = Object.entries(params ?? {})
    .filter(([, v]) => v !== undefined && v !== '')
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${v}`)
    .join('&');
  return qs ? `${url}?${qs}` : url;
}

async function readCache<T>(key: string): Promise<T | undefined> {
  const db = await openDb();
  if (!db) return undefined;
  const entry = await tx<Entry>(db, 'readonly', (s) => s.get(key));
  if (!entry || entry.v !== CACHE_VERSION || Date.now() - entry.savedAt > MAX_AGE_MS) return undefined;
  return entry.data as T;
}

async function writeCache(key: string, data: unknown) {
  const db = await openDb();
  if (db) await tx(db, 'readwrite', (s) => s.put({ key, data, savedAt: Date.now(), v: CACHE_VERSION } satisfies Entry));
}

/** Remove everything, e.g. after an admin edits places so other tabs don't show old data for long. */
export async function clearApiCache() {
  const db = await openDb();
  if (db) await tx(db, 'readwrite', (s) => s.clear());
}

/**
 * Calls onData with the cached copy (if any) and then with the network copy (if it differs).
 * Rejects only when there is neither a cached copy nor a network response.
 */
export async function cachedGet<T>(url: string, params: Params | undefined, onData: (data: T, fromCache: boolean) => void) {
  const key = cacheKey(url, params);
  const cached = await readCache<T>(key);
  if (cached !== undefined) onData(cached, true);
  try {
    const { data } = await api.get<T>(url, { params });
    if (cached === undefined || JSON.stringify(cached) !== JSON.stringify(data)) onData(data, false);
    writeCache(key, data);
  } catch (err) {
    if (cached === undefined) throw err;
  }
}
