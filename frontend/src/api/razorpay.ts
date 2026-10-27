/** Loads Razorpay Standard Checkout (checkout.js) on demand and opens it for a server-created order. */

export interface RazorpayOrder {
  provider: 'razorpay';
  test_mode: boolean;
  key_id: string;
  order_id: string;
  amount: number; // paise
  currency: string;
  name: string;
  description: string;
  prefill: { name: string; email: string; contact: string };
}

export interface RazorpaySuccess {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayInstance {
  open(): void;
  on(event: 'payment.failed', handler: (r: { error: { description?: string } }) => void): void;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayInstance;
  }
}

const SCRIPT_URL = 'https://checkout.razorpay.com/v1/checkout.js';
let loading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = SCRIPT_URL;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loading = null;
      reject(new Error('Could not load the payment window. Check your internet connection and try again.'));
    };
    document.body.appendChild(s);
  });
  return loading;
}

/**
 * Opens Razorpay Checkout. Resolves with the signed result on success, resolves null if the visitor closes it,
 * rejects when the payment fails. The caller must send the result to the server for signature verification.
 */
export async function openRazorpay(order: RazorpayOrder, brandColor: string): Promise<RazorpaySuccess | null> {
  await loadScript();
  return new Promise((resolve, reject) => {
    // Razorpay keeps its window open after a failed attempt so the visitor can retry with another method;
    // we only report the failure if they then close the window.
    let lastError: Error | null = null;
    const rzp = new window.Razorpay!({
      key: order.key_id,
      order_id: order.order_id,
      amount: order.amount,
      currency: order.currency,
      name: order.name,
      description: order.description,
      prefill: order.prefill,
      theme: { color: brandColor },
      handler: (result: RazorpaySuccess) => resolve(result),
      modal: { ondismiss: () => (lastError ? reject(lastError) : resolve(null)), confirm_close: true },
    });
    rzp.on('payment.failed', (r) => {
      lastError = new Error(r.error?.description || 'Payment failed. No money was taken.');
    });
    rzp.open();
  });
}
