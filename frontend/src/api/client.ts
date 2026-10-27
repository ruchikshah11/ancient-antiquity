import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const ACCESS = 'aa_access';
const REFRESH = 'aa_refresh';

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS);
  },
  get refresh() {
    return localStorage.getItem(REFRESH);
  },
  set(access: string, refresh?: string) {
    localStorage.setItem(ACCESS, access);
    if (refresh) localStorage.setItem(REFRESH, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  },
};

export const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? '/api' });

api.interceptors.request.use((config) => {
  const token = tokens.access;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing: Promise<string | null> | null = null;

async function refreshAccess(): Promise<string | null> {
  const refresh = tokens.refresh;
  if (!refresh) return null;
  try {
    const { data } = await axios.post(`${api.defaults.baseURL}/auth/refresh/`, { refresh });
    tokens.set(data.access, data.refresh);
    return data.access as string;
  } catch {
    tokens.clear();
    return null;
  }
}

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    if (error.response?.status === 401 && original && !original._retry && tokens.refresh) {
      original._retry = true;
      refreshing ??= refreshAccess().finally(() => (refreshing = null));
      const access = await refreshing;
      if (access) {
        original.headers.Authorization = `Bearer ${access}`;
        return api(original);
      }
    }
    return Promise.reject(error);
  },
);

/** Flatten a DRF error payload into one readable message. */
export function errorMessage(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  const data = (err as AxiosError)?.response?.data as unknown;
  if (!data) return fallback;
  if (typeof data === 'string') return data.length < 200 ? data : fallback;
  const parts: string[] = [];
  const walk = (v: unknown) => {
    if (typeof v === 'string') parts.push(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(data);
  return parts.join(' ') || fallback;
}
