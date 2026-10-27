import { api } from './client';

/** Plain `{ detail }` reply used by the notification and password-reset endpoints. */
export interface DetailResponse {
  detail: string;
}

export interface PasswordResetConfirmRequest {
  uid: string;
  token: string;
  new_password: string;
}

/** Email the ticket for a confirmed booking again (max 3 per hour per booking). */
export function resendTicketEmail(reference: string): Promise<DetailResponse> {
  return api.post<DetailResponse>(`/notifications/bookings/${encodeURIComponent(reference)}/resend/`).then((r) => r.data);
}

/** Ask for a reset link. The reply is the same whether or not the email has an account. */
export function requestPasswordReset(email: string): Promise<DetailResponse> {
  return api.post<DetailResponse>('/auth/password-reset/', { email }).then((r) => r.data);
}

export function confirmPasswordReset(body: PasswordResetConfirmRequest): Promise<DetailResponse> {
  return api.post<DetailResponse>('/auth/password-reset/confirm/', body).then((r) => r.data);
}
