import { api } from './client';
import type { User } from './types';

/** User payload with the sign-in extras the backend adds. */
export type AuthUser = User & {
  totp_enabled?: boolean;
  two_factor_setup_required?: boolean;
};

export interface LoginMethods {
  google_client_id: string | null;
  otp_email: boolean;
  otp_sms: boolean;
  password: boolean;
}

export interface TokenResult {
  access: string;
  refresh: string;
  user: AuthUser;
  created?: boolean;
}

export interface TwoFactorChallenge {
  two_factor_required: true;
  ticket: string;
}

/** Every sign-in endpoint answers with tokens, or a two-step challenge for users with an authenticator app. */
export type AuthResult = TokenResult | TwoFactorChallenge;

export const isChallenge = (r: AuthResult): r is TwoFactorChallenge =>
  (r as TwoFactorChallenge).two_factor_required === true;

/** Thrown by AuthContext.login when the password was right but a second step is needed. */
export class TwoFactorRequiredError extends Error {
  public readonly ticket: string;

  public constructor(ticket: string) {
    super('two_factor_required');
    this.ticket = ticket;
  }
}

let methodsPromise: Promise<LoginMethods> | null = null;

const PASSWORD_ONLY: LoginMethods = { google_client_id: null, otp_email: false, otp_sms: false, password: true };

/** Login methods, fetched once per page load (falls back to password only). */
export function getLoginMethods(): Promise<LoginMethods> {
  methodsPromise ??= api
    .get<LoginMethods>('/auth/methods/')
    .then((r) => r.data)
    .catch(() => {
      methodsPromise = null;
      return PASSWORD_ONLY;
    });
  return methodsPromise;
}

export type OtpTarget = { email: string } | { phone: string };

export const googleLogin = (credential: string) => api.post<AuthResult>('/auth/google/', { credential }).then((r) => r.data);
/** `dev_code` is only sent by a development server with no real SMS/email service connected. */
export const requestOtp = (target: OtpTarget) =>
  api.post<{ detail: string; expires_in_minutes: number; dev_code?: string }>('/auth/otp/request/', target).then((r) => r.data);

/** A verified mobile number with no account yet: finish sign-up with registerPhone(). */
export interface PhoneSignupRequired {
  register_required: true;
  phone_ticket: string;
  detail: string;
}

export const isPhoneSignup = (r: AuthResult | PhoneSignupRequired): r is PhoneSignupRequired =>
  (r as PhoneSignupRequired).register_required === true;

export const verifyOtp = (target: OtpTarget, code: string) =>
  api.post<AuthResult | PhoneSignupRequired>('/auth/otp/verify/', { ...target, code }).then((r) => r.data);

export const registerPhone = (input: { phone_ticket: string; first_name: string; last_name: string; email: string }) =>
  api.post<TokenResult>('/auth/otp/register/', input).then((r) => r.data);
export const verifyTwoFactor = (ticket: string, code: string) =>
  api.post<TokenResult>('/auth/2fa/verify/', { ticket, code }).then((r) => r.data);

// ---------------------------------------------------------------- two-step verification management

export interface TwoFactorStatus {
  enabled: boolean;
  backup_codes_left: number;
  required: boolean;
}

export const twoFactorStatus = () => api.get<TwoFactorStatus>('/auth/2fa/').then((r) => r.data);
export const twoFactorSetup = () =>
  api.post<{ secret: string; otpauth_uri: string }>('/auth/2fa/setup/').then((r) => r.data);
export const twoFactorEnable = (code: string) =>
  api.post<{ enabled: true; backup_codes: string[]; user: AuthUser }>('/auth/2fa/enable/', { code }).then((r) => r.data);
export const twoFactorDisable = (code: string) =>
  api.post<{ enabled: false; user: AuthUser }>('/auth/2fa/disable/', { code }).then((r) => r.data);
export const twoFactorBackupCodes = (code: string) =>
  api.post<{ backup_codes: string[] }>('/auth/2fa/backup-codes/', { code }).then((r) => r.data);

// ---------------------------------------------------------------- audit log (admin)

export type AuditAction = 'create' | 'update' | 'delete' | 'login' | 'login_failed' | 'other';

export interface AuditEntry {
  id: number;
  at: string;
  user: number | null;
  user_email: string | null;
  user_name: string;
  ip: string | null;
  method: string;
  path: string;
  action: AuditAction;
  object_repr: string;
  status_code: number | null;
  changes: unknown;
}

export interface AuditFilters {
  page?: number;
  user?: string;
  action?: string;
  from?: string;
  to?: string;
  search?: string;
}
