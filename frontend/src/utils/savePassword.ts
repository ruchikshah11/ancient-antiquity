/**
 * Ask the browser's password manager (Chrome / Google Password Manager, Edge, Safari …) to save a login.
 *
 * Sign-in happens without a page load, so browsers can't always tell a login succeeded and stay quiet.
 * Calling this right after a successful login, sign-up or password change makes Chrome show its
 * "Save password?" prompt. Browsers without the Credential Management API simply ignore it.
 */
type PasswordCredentialCtor = new (data: { id: string; password: string; name?: string }) => Credential;

export function offerToSavePassword(email: string, password: string, name?: string): void {
  const Ctor = (window as Window & { PasswordCredential?: PasswordCredentialCtor }).PasswordCredential;
  if (!Ctor || !email || !password || !navigator.credentials?.store) return;
  navigator.credentials.store(new Ctor({ id: email, password, name: name || undefined })).catch(() => undefined);
}
