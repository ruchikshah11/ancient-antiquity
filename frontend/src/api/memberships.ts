/** Annual membership ("Heritage Card"): plans, the visitor's cards and the admin screens. */
import { api } from './client';

export interface MembershipPlace {
  slug: string;
  name: string;
  city_name: string;
}

export interface MembershipPlan {
  id: number;
  name: string;
  slug: string;
  description: string;
  price: string;
  duration_days: number;
  discount_percent: number;
  free_entry: boolean;
  /** 100 with free entry, otherwise discount_percent. */
  benefit_percent: number;
  max_visitors_per_booking: number;
  /** Places where the card works; empty when all_places. */
  places: MembershipPlace[];
  all_places: boolean;
}

/** Admin view of a plan (GET/POST/PATCH /admin/membership-plans/). */
export interface AdminMembershipPlan extends MembershipPlan {
  is_active: boolean;
  sort: number;
  active_members: number;
  created_at: string;
  updated_at: string;
}

export type MembershipStatus = 'pending' | 'active' | 'expired' | 'cancelled';

export interface Membership {
  card_number: string;
  status: MembershipStatus;
  status_label: string;
  plan_name: string;
  plan_slug: string;
  discount_percent: number;
  free_entry: boolean;
  benefit_percent: number;
  max_visitors_per_booking: number;
  duration_days: number;
  holder_name: string;
  starts_on: string | null;
  ends_on: string | null;
  total_amount: string;
  payment_method: string;
  payment_id: string;
  gateway: string;
  paid_at: string | null;
  created_at: string;
  cancelled_at: string | null;
  hold_expires_at: string | null;
  refund_amount: string;
  refund_status: '' | 'pending' | 'processed' | 'failed';
  refund_status_label: string;
  user_email: string;
  /** Names of the places where the card works (empty = all places). */
  places: string[];
}

export const fetchPlans = (): Promise<MembershipPlan[]> => api.get<MembershipPlan[]>('/membership-plans/').then((r) => r.data);

export const fetchMyMemberships = (): Promise<Membership[]> => api.get<Membership[]>('/memberships/').then((r) => r.data);

/** The card valid today, or null. */
export const fetchCurrentMembership = (): Promise<Membership | null> =>
  api.get<{ membership: Membership | null }>('/memberships/current/').then((r) => r.data.membership);

export const buyMembership = (plan: string, holderName: string): Promise<Membership> =>
  api.post<Membership>('/memberships/', { plan, holder_name: holderName }).then((r) => r.data);
