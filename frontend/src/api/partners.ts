import type { Booking, GroupType } from './types';

/** Tour-operator portal, partner settlements and self-service kiosks (backend app `partners`). */

export type AgentStatus = 'pending' | 'approved' | 'rejected' | 'suspended';

export interface AgentProfile {
  id: number;
  email: string;
  name: string;
  role: string;
  company_name: string;
  gstin: string;
  contact_phone: string;
  city: string;
  message: string;
  commission_percent: string;
  credit_limit: string;
  balance: string;
  credit_available: string;
  status: AgentStatus;
  status_label: string;
  is_approved: boolean;
  approved_by_email: string | null;
  approved_at: string | null;
  admin_note: string;
  created_at: string;
}

export interface AgentDashboard {
  credit_limit: string;
  credit_used: string;
  credit_available: string;
  upcoming_visits: number;
  this_month: { bookings: number; visitors: number; gross: string; commission: string; net: string };
}

export interface AgentMe {
  profile: AgentProfile | null;
  dashboard: AgentDashboard | null;
}

export interface AgentApplyInput {
  company_name: string;
  gstin: string;
  contact_phone: string;
  city: string;
  message: string;
}

/** A booking as the tour operator sees it. */
export interface AgentBooking extends Omit<Booking, 'channel'> {
  channel: string;
  commission_amount: string;
  agent_can_cancel: boolean;
}

export interface AgentBookingInput {
  museum: string;
  slot: number;
  visit_date: string;
  items: { ticket_type: number; quantity: number }[];
  visitor_name: string;
  visitor_email?: string;
  visitor_phone?: string;
  group_type?: GroupType;
  organisation_name?: string;
  escort_count?: number;
}

export interface AgentPayment {
  id: number;
  amount: string;
  reference: string;
  note: string;
  received_on: string;
  recorded_by_email: string | null;
  created_at: string;
}

export interface StatementBooking {
  reference: string;
  created_at: string;
  museum_name: string;
  visit_date: string;
  slot_start: string;
  visitor_name: string;
  organisation_name: string;
  is_group: boolean;
  total_visitors: number;
  total_amount: string;
  commission_amount: string;
  status: string;
  status_label: string;
}

export interface AgentStatement {
  month: string;
  from: string;
  to: string;
  company_name: string;
  gstin: string;
  commission_percent: string;
  bookings: StatementBooking[];
  booking_count: number;
  visitors: number;
  cancelled_count: number;
  gross: string;
  commission: string;
  net_payable: string;
  payments: AgentPayment[];
  payments_received: string;
  outstanding_balance: string;
  credit_limit: string;
  credit_available: string;
}

export type SettlementStatus = 'draft' | 'approved' | 'paid';

export interface Settlement {
  id: number;
  museum_name: string;
  museum_slug: string;
  city_name: string;
  period_start: string;
  period_end: string;
  booking_count: number;
  visitor_count: number;
  gross_online: string;
  gross_kiosk: string;
  gross_counter: string;
  gross_agent: string;
  gross_total: string;
  refunds: string;
  platform_fee_percent: string;
  platform_fee: string;
  gst_on_fee: string;
  net_payable: string;
  status: SettlementStatus;
  status_label: string;
  approved_by_email: string | null;
  approved_at: string | null;
  paid_reference: string;
  paid_at: string | null;
  created_by_email: string | null;
  created_at: string;
}

export interface PartnerAccount {
  id: number;
  museum: string;
  museum_name: string;
  account_holder: string;
  bank_name: string;
  masked_account_number: string;
  ifsc: string;
  razorpay_account_id: string;
  platform_fee_percent: string;
  updated_at: string;
}

export interface SettlementDetail extends Settlement {
  by_channel: { channel: string; bookings: number; amount: string }[];
  bookings: { reference: string; paid_at: string; channel: string; visitors: number; amount: string }[];
  late_refunds: { reference: string; cancelled_at: string; amount: string }[];
  payout_account: PartnerAccount | null;
}

export interface GenerateResult {
  created: Settlement[];
  updated: Settlement[];
  skipped: { museum: string; reason: string }[];
}

export interface KioskDevice {
  id: number;
  name: string;
  email: string;
  museums: string[];
  museum_names: string[];
  is_active: boolean;
  last_login: string | null;
  created_at: string;
}

export interface KioskMe {
  id: number;
  name: string;
  museums: { slug: string; name: string; city_name: string; image_url: string }[];
}

export interface KioskSlot {
  id: number;
  start_time: string;
  end_time: string;
  running: boolean;
  available: number;
  bookable: boolean;
  closed_reason: string;
}

export interface KioskSession {
  museum: { slug: string; name: string; city_name: string; image_url: string };
  date: string;
  closed: boolean;
  closed_reason: string;
  tickets: { ticket_type: number; name: string; base_price: string; price: string; rule: string | null }[];
  slots: KioskSlot[];
}

export const CHANNEL_LABELS: Record<string, string> = {
  online: 'Online',
  counter: 'Counter',
  agent: 'Tour operator',
  kiosk: 'Kiosk',
};
