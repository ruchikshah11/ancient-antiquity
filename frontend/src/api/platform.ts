import { api } from './client';

/** Installable app + web push reminders (backend: notifications app). */

export interface PushPublicKey {
  /** VAPID public key (base64url); null when the server has no push keys configured. */
  public_key: string | null;
}

export function getPushPublicKey(): Promise<PushPublicKey> {
  return api.get<PushPublicKey>('/notifications/push/public-key/').then((r) => r.data);
}

/** Body is PushSubscription.toJSON(): { endpoint, keys: { p256dh, auth } }. */
export function savePushSubscription(subscription: PushSubscriptionJSON): Promise<{ subscribed: boolean }> {
  return api.post<{ subscribed: boolean }>('/notifications/push/subscribe/', subscription).then((r) => r.data);
}

export function deletePushSubscription(endpoint: string): Promise<{ subscribed: boolean; removed: number }> {
  return api
    .post<{ subscribed: boolean; removed: number }>('/notifications/push/unsubscribe/', { endpoint })
    .then((r) => r.data);
}

/** True when this browser can receive web push (needs a service worker, PushManager and Notification). */
export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

/** VAPID keys are base64url; PushManager.subscribe wants the raw bytes. */
export function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

/** The app's service worker registration, registering /sw.js if needed (main.tsx registers it in production only). */
export async function getServiceWorker(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration('/');
  if (existing) return existing;
  await navigator.serviceWorker.register('/sw.js');
  return navigator.serviceWorker.ready;
}
