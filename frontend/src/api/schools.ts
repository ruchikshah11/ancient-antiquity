import { api } from './client';
import type {
  Paginated,
  School,
  SchoolBoard,
  SchoolEstimate,
  SchoolInput,
  SchoolStatus,
  SchoolTrip,
  SchoolTripInput,
  SchoolTripSlots,
  SchoolTripStatus,
} from './types';

/** School trip portal: schools registered by teachers, verified by admins; class trips approved by staff. */

export const MIN_STUDENTS = 10;
export const MAX_STUDENTS = 400;
export const STUDENTS_PER_TEACHER = 20;
export const WINDOW_DAYS = 90;

export const SCHOOL_BOARDS: SchoolBoard[] = ['cbse', 'icse', 'state', 'ib', 'other'];

export const SCHOOL_STATUS_BG: Record<SchoolStatus, string> = {
  pending: 'bg-warning text-dark',
  verified: 'bg-success',
  rejected: 'bg-danger',
};

export const TRIP_STATUSES: { value: SchoolTripStatus; label: string; bg: string }[] = [
  { value: 'submitted', label: 'Submitted', bg: 'bg-secondary' },
  { value: 'approved', label: 'Approved', bg: 'bg-info text-dark' },
  { value: 'completed', label: 'Completed', bg: 'bg-success' },
  { value: 'declined', label: 'Declined', bg: 'bg-danger' },
  { value: 'cancelled', label: 'Cancelled', bg: 'bg-dark' },
];

export const tripStatus = (s: SchoolTripStatus) =>
  TRIP_STATUSES.find((x) => x.value === s) ?? { value: s, label: s, bg: 'bg-secondary' };

export const teachersNeeded = (students: number): number => Math.ceil(Math.max(students, 0) / STUDENTS_PER_TEACHER);

/** The signed-in teacher's school, or null when none is registered yet (404). */
export async function getMySchool(): Promise<School | null> {
  try {
    const { data } = await api.get<School>('/schools/mine/');
    return data;
  } catch (err) {
    if ((err as { response?: { status?: number } })?.response?.status === 404) return null;
    throw err;
  }
}

export const registerSchool = (input: SchoolInput) => api.post<School>('/schools/mine/', input).then((r) => r.data);
export const updateSchool = (input: Partial<SchoolInput>) => api.patch<School>('/schools/mine/', input).then((r) => r.data);

export interface EstimateInput {
  museum: string;
  date?: string;
  students: number;
  young_students: number;
  teachers: number;
  helpers: number;
}

export const estimateTrip = (input: EstimateInput) => api.post<SchoolEstimate>('/schools/estimate/', input).then((r) => r.data);

export const listTrips = (params: Record<string, string | number | undefined>) =>
  api.get<Paginated<SchoolTrip>>('/schools/trips/', { params }).then((r) => r.data);
export const createTrip = (input: SchoolTripInput) => api.post<SchoolTrip>('/schools/trips/', input).then((r) => r.data);
export const cancelTrip = (id: number) => api.post<SchoolTrip>(`/schools/trips/${id}/cancel/`).then((r) => r.data);

// --- staff / admin ---------------------------------------------------------------------------------

export interface ApproveTripInput {
  date?: string;
  slot?: number | null;
  quoted_amount?: string | null;
  staff_note?: string;
}

export const tripEstimate = (id: number, date?: string) =>
  api.get<SchoolEstimate>(`/schools/trips/${id}/estimate/`, { params: { date } }).then((r) => r.data);
export const tripSlots = (id: number, date?: string) =>
  api.get<SchoolTripSlots>(`/schools/trips/${id}/slots/`, { params: { date } }).then((r) => r.data);
export const approveTrip = (id: number, input: ApproveTripInput) =>
  api.post<SchoolTrip>(`/schools/trips/${id}/approve/`, input).then((r) => r.data);
export const declineTrip = (id: number, reason: string) =>
  api.post<SchoolTrip>(`/schools/trips/${id}/decline/`, { reason }).then((r) => r.data);
export const completeTrip = (id: number) => api.post<SchoolTrip>(`/schools/trips/${id}/complete/`).then((r) => r.data);

export const listSchools = (params: Record<string, string | number | undefined>) =>
  api.get<Paginated<School>>('/schools/', { params }).then((r) => r.data);
export const verifySchool = (id: number) => api.post<School>(`/schools/${id}/verify/`).then((r) => r.data);
export const rejectSchool = (id: number, reason: string) =>
  api.post<School>(`/schools/${id}/reject/`, { reason }).then((r) => r.data);
