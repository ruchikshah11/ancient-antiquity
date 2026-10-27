import { api } from './client';

/* Types for panel reports, staff place assignments and GST invoices. */

export interface ReportDay {
  date: string;
  bookings: number;
  visitors: number;
  revenue: number;
  refunds: number;
}

export interface ReportSplit {
  key: string | boolean;
  label: string;
  bookings: number;
  visitors: number;
  revenue: number;
}

export interface ReportMuseumRow {
  slug: string;
  name: string;
  city: string;
  state: string;
  bookings: number;
  visitors: number;
  revenue: number;
}

export interface ReportSummary {
  from: string;
  to: string;
  museum: { slug: string; name: string } | null;
  totals: {
    bookings: number;
    visitors: number;
    revenue: number;
    refunds: number;
    discounts: number;
    addons?: number;
    membership_discounts?: number;
    cancelled: number;
    net: number;
  };
  daily: ReportDay[];
  by_channel: ReportSplit[];
  by_type: ReportSplit[];
  by_museum: ReportMuseumRow[];
}

export interface ReportFilters {
  from: string;
  to: string;
  museum?: string;
}

/** Download an export with the auth header, then hand it to the browser as a file. */
export async function downloadReport(kind: 'csv' | 'xlsx', filters: ReportFilters): Promise<void> {
  const res = await api.get<Blob>(`/admin/reports/bookings.${kind}`, {
    params: { from: filters.from, to: filters.to, museum: filters.museum || undefined },
    responseType: 'blob',
  });
  const disposition = String(res.headers['content-disposition'] ?? '');
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? `bookings.${kind}`;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface AssignedMuseum {
  slug: string;
  name: string;
  city_name: string;
  state_name: string;
}

export interface StaffMuseums {
  user: number;
  email: string;
  museums: AssignedMuseum[];
}

export interface InvoiceItem {
  description: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface Invoice {
  invoice_number: string;
  invoice_date: string;
  reference: string;
  seller: { name: string; address: string; gstin: string; email: string };
  buyer: { name: string; email: string; phone: string; organisation: string; group_type: string };
  place: { name: string; address: string; city: string; state: string };
  place_of_supply: string;
  visit_date: string;
  slot_start: string;
  slot_end: string;
  total_visitors: number;
  items: InvoiceItem[];
  subtotal: number;
  discount: number;
  group_discount?: number;
  promo_discount?: number;
  promo_code?: string;
  voucher_amount?: number;
  paid_online?: number;
  total: number;
  taxable_value: number;
  gst_percent: number;
  cgst_percent: number;
  cgst: number;
  sgst_percent: number;
  sgst: number;
  gst_total: number;
  payment: { method: string; payment_id: string; paid_at: string | null; channel: string };
  status: string;
  status_label: string;
  notes: string[];
}
