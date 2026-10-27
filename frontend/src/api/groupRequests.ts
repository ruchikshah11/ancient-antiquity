import type { Booking, GroupType } from './types';

/** Large group visits (more than the instant-group maximum): requested by visitors, approved by staff. */

export type GroupRequestStatus = 'submitted' | 'under_review' | 'approved' | 'declined' | 'paid' | 'cancelled' | 'expired';
export type PreferredTime = 'morning' | 'afternoon' | 'any';
export type PaymentMode = 'online' | 'invoice';

export const GROUP_REQUEST_MAX = 1000;

export const PREFERRED_TIMES: { value: PreferredTime; label: string }[] = [
  { value: 'any', label: 'Any time' },
  { value: 'morning', label: 'Morning (before noon)' },
  { value: 'afternoon', label: 'Afternoon' },
];

export const GROUP_REQUEST_STATUSES: { value: GroupRequestStatus; label: string; bg: string }[] = [
  { value: 'submitted', label: 'Submitted', bg: 'bg-secondary' },
  { value: 'under_review', label: 'Under review', bg: 'bg-info text-dark' },
  { value: 'approved', label: 'Approved – awaiting payment', bg: 'bg-warning text-dark' },
  { value: 'paid', label: 'Paid', bg: 'bg-success' },
  { value: 'declined', label: 'Declined', bg: 'bg-danger' },
  { value: 'cancelled', label: 'Cancelled', bg: 'bg-dark' },
  { value: 'expired', label: 'Expired', bg: 'bg-danger' },
];

export const groupRequestStatus = (s: GroupRequestStatus) =>
  GROUP_REQUEST_STATUSES.find((x) => x.value === s) ?? { value: s, label: s, bg: 'bg-secondary' };

export interface GroupRequest {
  id: number;
  reference: string;
  museum_name: string;
  museum_slug: string;
  city_name: string;
  preferred_date: string;
  alternative_date: string | null;
  preferred_time: PreferredTime;
  preferred_time_label: string;
  group_type: GroupType;
  group_type_label: string;
  organisation_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  participants: number;
  escorts: number;
  needs_guide: boolean;
  notes: string;
  status: GroupRequestStatus;
  status_label: string;
  staff_notes: string;
  quoted_total: string | null;
  discount_percent: number | null;
  approved_date: string | null;
  decided_by_email: string | null;
  decided_at: string | null;
  payment_mode: PaymentMode | '';
  payment_mode_label: string;
  pay_by: string | null;
  requester_email: string;
  created_at: string;
  updated_at: string;
  bookings: Booking[];
  can_cancel: boolean;
}

export interface GroupRequestInput {
  museum: string;
  preferred_date: string;
  alternative_date?: string | null;
  preferred_time: PreferredTime;
  group_type: GroupType;
  organisation_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  participants: number;
  escorts: number;
  needs_guide: boolean;
  notes: string;
}

export interface PlanSlot {
  slot_id: number;
  start: string;
  end: string;
  capacity: number;
  free: number;
  /** Free places minus the share kept for individual visitors. */
  usable: number;
}

export interface PlanAllocation {
  slot_id: number;
  start: string;
  end: string;
  people: number;
  participants: number;
  escorts: number;
}

export interface PlanTicketType {
  id: number;
  name: string;
  price: string;
}

export interface GroupPlan {
  fits: boolean;
  people: number;
  allocated: number;
  date: string;
  note: string;
  preferred_time: PreferredTime;
  reserve_percent: number;
  slots: PlanSlot[];
  allocations: PlanAllocation[];
  default_ticket_type: PlanTicketType | null;
  default_discount_percent: number;
  ticket_types: PlanTicketType[];
}

export interface ApproveInput {
  date: string;
  allocations: { slot: number; participants: number; escorts: number }[];
  ticket_type?: number;
  discount_percent: number;
  payment_mode: PaymentMode;
  pay_by?: string;
  staff_notes?: string;
}
