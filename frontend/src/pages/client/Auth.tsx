import type { AxiosError } from 'axios';
import * as React from 'react';
import { Link } from 'react-router-dom';
import {
  AuthResult,
  getLoginMethods,
  isChallenge,
  isPhoneSignup,
  LoginMethods,
  OtpTarget,
  registerPhone,
  requestOtp,
  TokenResult,
  TwoFactorRequiredError,
  verifyOtp,
  verifyTwoFactor,
} from '../../api/auth2';
import { errorMessage } from '../../api/client';
import type { User } from '../../api/types';
import GoogleButton from '../../components/GoogleButton';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import { offerToSavePassword } from '../../utils/savePassword';

export interface Prefill {
  name?: string;
  email?: string;
  phone?: string;
}

interface AuthFormProps extends WithAuthProps, WithI18nProps {
  onDone: (u: User) => void;
  onSwitch?: () => void;
  prefill?: Prefill;
}

type LoginFormProps = AuthFormProps;

type LoginMode = 'password' | 'email' | 'sms';

interface TwoFactorStepProps extends WithI18nProps {
  ticket: string;
  onTokens: (data: TokenResult) => void;
  onCancel: (message?: string) => void;
}

interface TwoFactorStepState {
  code: string;
  error: string;
  busy: boolean;
}

/** Second sign-in step for accounts with an authenticator app (6-digit code or a backup code). */
class TwoFactorStepBase extends React.Component<TwoFactorStepProps, TwoFactorStepState> {
  public state: TwoFactorStepState = { code: '', error: '', busy: false };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { t } = this.props.i18n;
    this.setState({ busy: true, error: '' });
    try {
      this.props.onTokens(await verifyTwoFactor(this.props.ticket, this.state.code));
    } catch (err) {
      const data = (err as AxiosError<{ expired?: boolean }>).response?.data;
      if (data?.expired) {
        this.props.onCancel(t('auth2.twoFactor.expired'));
        return;
      }
      if (this.mounted) this.setState({ error: errorMessage(err, t('auth2.twoFactor.wrong')), code: '' });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { code, error, busy } = this.state;
    return (
      <form onSubmit={this.submit}>
        <div className="text-center mb-3">
          <i className="bi bi-shield-lock display-6 text-primary" aria-hidden="true" />
          <h3 className="h5 mt-2 mb-1">{t('auth2.twoFactor.title')}</h3>
          <p className="text-muted small mb-0">{t('auth2.twoFactor.intro')}</p>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        <div className="mb-3">
          <label htmlFor="tf-code" className="form-label">{t('auth2.twoFactor.code')}</label>
          <input
            id="tf-code"
            className="form-control form-control-lg text-center"
            style={{ letterSpacing: '0.3em' }}
            value={code}
            onChange={(e) => this.setState({ code: e.target.value.slice(0, 12) })}
            inputMode="text"
            autoComplete="one-time-code"
            required
            autoFocus
          />
          <div className="form-text">{t('auth2.twoFactor.backupHint')}</div>
        </div>
        <button className="btn btn-accent btn-lg w-100" disabled={busy || code.trim().length < 6}>
          {busy ? t('auth2.verifying') : t('auth2.twoFactor.submit')}
        </button>
        <div className="text-center mt-3">
          <button type="button" className="btn btn-link btn-sm" onClick={() => this.props.onCancel()}>
            <i className="bi bi-arrow-left me-1" aria-hidden="true" />
            {t('auth2.back')}
          </button>
        </div>
      </form>
    );
  }
}

const TwoFactorStep = withI18n(TwoFactorStepBase);

interface OrDividerProps extends WithI18nProps {}

class OrDividerBase extends React.Component<OrDividerProps> {
  public render(): React.ReactNode {
    return (
      <div className="d-flex align-items-center my-3 text-muted small" role="separator">
        <hr className="flex-grow-1 my-0" />
        <span className="px-3">{this.props.i18n.t('auth2.or')}</span>
        <hr className="flex-grow-1 my-0" />
      </div>
    );
  }
}

const OrDivider = withI18n(OrDividerBase);

interface LoginFormState {
  methods: LoginMethods | null;
  mode: LoginMode;
  email: string;
  password: string;
  phone: string;
  code: string;
  codeSent: boolean;
  info: string;
  error: string;
  registerHint: boolean;
  busy: boolean;
  ticket: string | null;
  /** Development server only: the code, shown because no SMS/email service is connected. */
  devCode: string;
  /** Set after a new mobile number is verified: finish sign-up with name + email. */
  phoneTicket: string | null;
  signup: { first_name: string; last_name: string; email: string };
}

class LoginFormBase extends React.Component<LoginFormProps, LoginFormState> {
  public state: LoginFormState = {
    methods: null,
    mode: 'password',
    email: this.props.prefill?.email ?? '',
    password: '',
    phone: this.props.prefill?.phone ?? '',
    code: '',
    codeSent: false,
    info: '',
    error: '',
    registerHint: false,
    busy: false,
    ticket: null,
    devCode: '',
    phoneTicket: null,
    signup: { first_name: '', last_name: '', email: this.props.prefill?.email ?? '' },
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    getLoginMethods().then((methods) => this.mounted && this.setState({ methods }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private finish = (result: AuthResult): void => {
    if (isChallenge(result)) {
      if (this.mounted) this.setState({ ticket: result.ticket, error: '', info: '' });
      return;
    }
    const user = this.props.auth.loginWithTokens(result);
    if (this.state.password) offerToSavePassword(this.state.email, this.state.password);  // finished a 2-step login
    this.props.onDone(user);
  };

  private onTokens = (data: TokenResult): void => {
    this.props.onDone(this.props.auth.loginWithTokens(data));
  };

  private cancelTwoFactor = (message?: string): void => {
    this.setState({ ticket: null, password: '', code: '', codeSent: false, error: message ?? '' });
  };

  private setMode = (mode: LoginMode): void => {
    this.setState({ mode, code: '', codeSent: false, info: '', error: '', registerHint: false, devCode: '', phoneTicket: null });
  };

  private target(): OtpTarget {
    return this.state.mode === 'sms' ? { phone: this.state.phone } : { email: this.state.email };
  }

  private submitPassword = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    this.setState({ busy: true, error: '' });
    try {
      const user = await this.props.auth.login(this.state.email, this.state.password);
      offerToSavePassword(this.state.email, this.state.password);
      this.props.onDone(user);
    } catch (err) {
      if (err instanceof TwoFactorRequiredError) {
        if (this.mounted) this.setState({ ticket: err.ticket });
      } else if (this.mounted) {
        this.setState({ error: errorMessage(err, this.props.i18n.t('account.login.invalid')) });
      }
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  private sendCode = async (): Promise<void> => {
    const { t } = this.props.i18n;
    this.setState({ busy: true, error: '', info: '', registerHint: false });
    try {
      const r = await requestOtp(this.target());
      if (this.mounted) {
        this.setState({
          codeSent: true,
          code: '',
          devCode: r.dev_code ?? '',
          info: t(this.state.mode === 'sms' ? 'auth2.otp.sentSms' : 'auth2.otp.sentEmail', { minutes: r.expires_in_minutes }),
        });
      }
    } catch (err) {
      const status = (err as AxiosError).response?.status;
      if (this.mounted) this.setState({ error: status === 429 ? t('auth2.otp.tooMany') : errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  private submitCode = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (!this.state.codeSent) {
      await this.sendCode();
      return;
    }
    const { t } = this.props.i18n;
    this.setState({ busy: true, error: '', registerHint: false });
    try {
      const result = await verifyOtp(this.target(), this.state.code.trim());
      if (isPhoneSignup(result)) {
        // New mobile number: one more step (name + email) to create the account.
        if (this.mounted) this.setState({ phoneTicket: result.phone_ticket, info: '', error: '', devCode: '' });
        return;
      }
      this.finish(result);
    } catch (err) {
      const data = (err as AxiosError<{ register_required?: boolean }>).response?.data;
      if (this.mounted) {
        if (data?.register_required) this.setState({ error: t('auth2.otp.noAccountForPhone'), registerHint: true });
        else this.setState({ error: errorMessage(err, t('auth2.otp.wrong')) });
      }
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  private submitSignup = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { phoneTicket, signup } = this.state;
    if (!phoneTicket) return;
    this.setState({ busy: true, error: '' });
    try {
      this.onTokens(await registerPhone({ phone_ticket: phoneTicket, ...signup }));
    } catch (err) {
      const data = (err as AxiosError<{ expired?: boolean }>).response?.data;
      if (this.mounted) {
        this.setState({ error: errorMessage(err) });
        if (data?.expired) this.setState({ phoneTicket: null, codeSent: false, code: '' });
      }
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  private setSignup = (key: 'first_name' | 'last_name' | 'email') => (e: React.ChangeEvent<HTMLInputElement>): void => {
    const value = e.target.value;
    this.setState((s) => ({ signup: { ...s.signup, [key]: value } }));
  };

  private renderPhoneSignup(): React.ReactNode {
    const { t } = this.props.i18n;
    const { signup, busy } = this.state;
    return (
      <form onSubmit={this.submitSignup}>
        <div className="alert alert-success d-flex gap-2 align-items-start">
          <i className="bi bi-check-circle-fill mt-1" aria-hidden="true" />
          <div>
            <strong className="d-block">{t('auth2.signup.title')}</strong>
            <span className="small">{t('auth2.signup.intro')}</span>
          </div>
        </div>
        <div className="row g-2 mb-3">
          <div className="col-sm-6">
            <label htmlFor="ps-first" className="form-label">{t('auth2.signup.firstName')}</label>
            <input id="ps-first" className="form-control" value={signup.first_name} onChange={this.setSignup('first_name')} required autoComplete="given-name" autoFocus />
          </div>
          <div className="col-sm-6">
            <label htmlFor="ps-last" className="form-label">{t('auth2.signup.lastName')}</label>
            <input id="ps-last" className="form-control" value={signup.last_name} onChange={this.setSignup('last_name')} autoComplete="family-name" />
          </div>
        </div>
        <div className="mb-4">
          <label htmlFor="ps-email" className="form-label">{t('auth2.signup.email')}</label>
          <input id="ps-email" type="email" className="form-control" value={signup.email} onChange={this.setSignup('email')} required autoComplete="email" />
        </div>
        <button className="btn btn-accent btn-lg w-100" disabled={busy}>{busy ? t('auth2.wait') : t('auth2.signup.submit')}</button>
        <div className="text-center mt-2">
          <button type="button" className="btn btn-link btn-sm" onClick={() => this.setState({ phoneTicket: null, codeSent: false, code: '', error: '' })}>
            {t('auth2.signup.back')}
          </button>
        </div>
      </form>
    );
  }

  private onGoogleError = (message: string): void => {
    this.setState({ error: message });
  };

  private renderPassword(): React.ReactNode {
    const { t } = this.props.i18n;
    const { email, password, busy } = this.state;
    return (
      <form onSubmit={this.submitPassword}>
        <div className="mb-3">
          <label htmlFor="login-email" className="form-label">{t('account.email')}</label>
          <input id="login-email" name="username" type="email" className="form-control" value={email} onChange={(e) => this.setState({ email: e.target.value })} required autoComplete="username" autoFocus />
        </div>
        <div className="mb-4">
          <label htmlFor="login-password" className="form-label">{t('account.password')}</label>
          <input id="login-password" name="password" type="password" className="form-control" value={password} onChange={(e) => this.setState({ password: e.target.value })} required autoComplete="current-password" />
          <div className="text-end mt-1">
            <Link to="/forgot-password" className="small">{t('account.login.forgot')}</Link>
          </div>
        </div>
        <button className="btn btn-accent btn-lg w-100" disabled={busy}>{busy ? t('account.login.busy') : t('account.login.submit')}</button>
      </form>
    );
  }

  private renderCode(): React.ReactNode {
    const { t } = this.props.i18n;
    const { onSwitch } = this.props;
    const { mode, email, phone, code, codeSent, busy, registerHint, devCode, phoneTicket } = this.state;
    const sms = mode === 'sms';
    if (phoneTicket) return this.renderPhoneSignup();
    return (
      <form onSubmit={this.submitCode}>
        <div className="mb-3">
          {sms ? (
            <>
              <label htmlFor="otp-phone" className="form-label">{t('account.mobileNumber')}</label>
              <input id="otp-phone" className="form-control" inputMode="tel" value={phone} onChange={(e) => this.setState({ phone: e.target.value, codeSent: false, code: '' })} placeholder="9876543210" required autoComplete="tel" autoFocus readOnly={codeSent} />
            </>
          ) : (
            <>
              <label htmlFor="otp-email" className="form-label">{t('account.email')}</label>
              <input id="otp-email" type="email" className="form-control" value={email} onChange={(e) => this.setState({ email: e.target.value, codeSent: false, code: '' })} required autoComplete="email" autoFocus readOnly={codeSent} />
            </>
          )}
          {codeSent && (
            <button type="button" className="btn btn-link btn-sm px-0" onClick={() => this.setState({ codeSent: false, code: '', info: '' })}>
              {t(sms ? 'auth2.otp.changePhone' : 'auth2.otp.changeEmail')}
            </button>
          )}
        </div>
        {codeSent && devCode && (
          <div className="alert alert-warning small d-flex gap-2 align-items-center" role="status">
            <i className="bi bi-tools" aria-hidden="true" />
            <span>{t('auth2.otp.devCode', { code: devCode })}</span>
            <button type="button" className="btn btn-sm btn-outline-dark ms-auto" onClick={() => this.setState({ code: devCode })}>
              {t('auth2.otp.code')}
            </button>
          </div>
        )}
        {codeSent && (
          <div className="mb-3">
            <label htmlFor="otp-code" className="form-label">{t('auth2.otp.code')}</label>
            <input
              id="otp-code"
              className="form-control form-control-lg text-center"
              style={{ letterSpacing: '0.4em' }}
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(e) => this.setState({ code: e.target.value.replace(/\D/g, '').slice(0, 6) })}
              autoComplete="one-time-code"
              required
              autoFocus
            />
            <div className="d-flex justify-content-between align-items-center mt-1">
              <span className="form-text mt-0">{t(sms ? 'auth2.otp.codeHelpSms' : 'auth2.otp.codeHelp')}</span>
              <button type="button" className="btn btn-link btn-sm px-0" disabled={busy} onClick={this.sendCode}>
                <i className="bi bi-arrow-repeat me-1" aria-hidden="true" />
                {t('auth2.otp.resend')}
              </button>
            </div>
          </div>
        )}
        <button className="btn btn-accent btn-lg w-100" disabled={busy || (codeSent && code.length !== 6)}>
          {busy ? t('auth2.wait') : codeSent ? t('auth2.otp.verify') : t('auth2.otp.send')}
        </button>
        {!codeSent && <p className="form-text text-center mt-2 mb-0">{t(sms ? 'auth2.otp.introSms' : 'auth2.otp.introEmail')}</p>}
        {registerHint && onSwitch && (
          <div className="text-center mt-2">
            <button type="button" className="btn btn-outline-primary btn-sm" onClick={onSwitch}>{t('account.login.createFree')}</button>
          </div>
        )}
      </form>
    );
  }

  public render(): React.ReactNode {
    const { onSwitch } = this.props;
    const { t } = this.props.i18n;
    const { methods, mode, error, info, ticket } = this.state;

    if (ticket) {
      return (
        <>
          {error && <div className="alert alert-danger">{error}</div>}
          <TwoFactorStep ticket={ticket} onTokens={this.onTokens} onCancel={this.cancelTwoFactor} />
        </>
      );
    }

    const modes: { key: LoginMode; icon: string; label: string }[] = [{ key: 'password', icon: 'key', label: t('auth2.mode.password') }];
    if (methods?.otp_email) modes.push({ key: 'email', icon: 'envelope', label: t('auth2.mode.email') });
    if (methods?.otp_sms) modes.push({ key: 'sms', icon: 'phone', label: t('auth2.mode.sms') });

    return (
      <div>
        {error && <div className="alert alert-danger">{error}</div>}
        {info && !error && <div className="alert alert-info py-2 small">{info}</div>}
        {methods?.google_client_id && (
          <>
            <GoogleButton clientId={methods.google_client_id} text="signin_with" onResult={this.finish} onError={this.onGoogleError} />
            <OrDivider />
          </>
        )}
        {modes.length > 1 && (
          <div className="btn-group w-100 mb-3" role="group" aria-label={t('auth2.mode.label')}>
            {modes.map((m) => (
              <button
                key={m.key}
                type="button"
                className={`btn btn-sm ${mode === m.key ? 'btn-primary' : 'btn-outline-primary'}`}
                aria-pressed={mode === m.key}
                onClick={() => this.setMode(m.key)}
              >
                <i className={`bi bi-${m.icon} me-1`} aria-hidden="true" />
                {m.label}
              </button>
            ))}
          </div>
        )}
        {mode === 'password' ? this.renderPassword() : this.renderCode()}
        {onSwitch && (
          <p className="text-muted small text-center mt-3 mb-0">
            {t('account.login.newVisitor')}{' '}
            <button type="button" className="btn btn-link p-0 align-baseline small" onClick={onSwitch}>{t('account.login.createFree')}</button>
          </p>
        )}
      </div>
    );
  }
}

export const LoginForm = withAuth(withI18n(LoginFormBase));

type RegisterFormProps = AuthFormProps;

interface RegisterFormFields {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  password: string;
}

interface RegisterFormState {
  form: RegisterFormFields;
  error: string;
  busy: boolean;
  methods: LoginMethods | null;
  ticket: string | null;
}

class RegisterFormBase extends React.Component<RegisterFormProps, RegisterFormState> {
  public state: RegisterFormState = RegisterFormBase.initialState(this.props.prefill);

  private mounted = false;

  private static initialState(prefill?: Prefill): RegisterFormState {
    const [first, ...rest] = (prefill?.name ?? '').trim().split(/\s+/);
    return {
      form: {
        first_name: first ?? '',
        last_name: rest.join(' '),
        email: prefill?.email ?? '',
        phone: prefill?.phone ?? '',
        password: '',
      },
      error: '',
      busy: false,
      methods: null,
      ticket: null,
    };
  }

  public componentDidMount(): void {
    this.mounted = true;
    getLoginMethods().then((methods) => this.mounted && this.setState({ methods }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private onGoogle = (result: AuthResult): void => {
    if (isChallenge(result)) {
      this.setState({ ticket: result.ticket, error: '' });
      return;
    }
    this.props.onDone(this.props.auth.loginWithTokens(result));
  };

  private onTokens = (data: TokenResult): void => {
    this.props.onDone(this.props.auth.loginWithTokens(data));
  };

  private set = (k: keyof RegisterFormFields) => (e: React.ChangeEvent<HTMLInputElement>): void =>
    this.setState({ form: { ...this.state.form, [k]: e.target.value } });

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    this.setState({ busy: true, error: '' });
    try {
      const user = await this.props.auth.register(this.state.form);
      offerToSavePassword(this.state.form.email, this.state.form.password, `${this.state.form.first_name} ${this.state.form.last_name}`.trim());
      this.props.onDone(user);
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { onSwitch } = this.props;
    const { t } = this.props.i18n;
    const { form, error, busy, methods, ticket } = this.state;
    if (ticket) {
      return <TwoFactorStep ticket={ticket} onTokens={this.onTokens} onCancel={(m?: string) => this.setState({ ticket: null, error: m ?? '' })} />;
    }
    return (
      <form onSubmit={this.submit}>
        {error && <div className="alert alert-danger">{error}</div>}
        {methods?.google_client_id && (
          <>
            <GoogleButton clientId={methods.google_client_id} text="signup_with" onResult={this.onGoogle} onError={(m: string) => this.setState({ error: m })} />
            <OrDivider />
          </>
        )}
        <div className="row g-3 mb-3">
          <div className="col-sm-6">
            <label htmlFor="reg-fn" className="form-label">{t('account.firstName')}</label>
            <input id="reg-fn" className="form-control" value={form.first_name} onChange={this.set('first_name')} required autoFocus />
          </div>
          <div className="col-sm-6">
            <label htmlFor="reg-ln" className="form-label">{t('account.lastName')}</label>
            <input id="reg-ln" className="form-control" value={form.last_name} onChange={this.set('last_name')} />
          </div>
        </div>
        <div className="mb-3">
          <label htmlFor="reg-em" className="form-label">{t('account.email')}</label>
          <input id="reg-em" name="username" type="email" className="form-control" value={form.email} onChange={this.set('email')} required autoComplete="username" />
        </div>
        <div className="mb-3">
          <label htmlFor="reg-ph" className="form-label">{t('account.mobileNumber')}</label>
          <input id="reg-ph" className="form-control" inputMode="tel" value={form.phone} onChange={this.set('phone')} placeholder="9876543210" />
        </div>
        <div className="mb-4">
          <label htmlFor="reg-pw" className="form-label">{t('account.password')}</label>
          <input id="reg-pw" name="new-password" type="password" className="form-control" value={form.password} onChange={this.set('password')} required minLength={8} autoComplete="new-password" aria-describedby="reg-pw-help" />
          <div id="reg-pw-help" className="form-text">{t('account.passwordHelp')}</div>
        </div>
        <button className="btn btn-accent btn-lg w-100" disabled={busy}>{busy ? t('account.register.busy') : t('account.register.submit')}</button>
        {onSwitch && (
          <p className="text-muted small text-center mt-3 mb-0">
            {t('account.register.already')} <button type="button" className="btn btn-link p-0 align-baseline small" onClick={onSwitch}>{t('account.login.submit')}</button>
          </p>
        )}
      </form>
    );
  }
}

export const RegisterForm = withAuth(withI18n(RegisterFormBase));

/** Where to go after logging in / registering: back to `state.from`, else the panel or home. */
function afterAuth(router: WithRouterProps['router'], u: User): void {
  const from = (router.location.state as { from?: string } | null)?.from;
  router.navigate(from ?? (u.is_panel_user ? '/admin' : u.role === 'partner' ? '/partner' : '/'), { replace: true });
}

type LoginProps = WithRouterProps & WithI18nProps;

class LoginBase extends React.Component<LoginProps> {
  private done = (u: User): void => afterAuth(this.props.router, u);

  private switchToRegister = (): void => {
    const { router } = this.props;
    router.navigate('/register', { state: router.location.state, replace: true });
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <div className="container page py-4 py-lg-5">
        <div className="row">
          <div className="col-md-6 col-lg-5 mx-auto">
            <div className="card border-0 shadow-sm">
              <div className="card-body p-4 p-lg-5">
                <h2 className="mb-1">{t('account.login.title')}</h2>
                <p className="text-muted mb-4">{t('account.login.intro')}</p>
                <LoginForm onDone={this.done} onSwitch={this.switchToRegister} />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

export const Login = withRouter(withI18n(LoginBase));

type RegisterProps = WithRouterProps & WithI18nProps;

class RegisterBase extends React.Component<RegisterProps> {
  private done = (u: User): void => afterAuth(this.props.router, u);

  private switchToLogin = (): void => {
    const { router } = this.props;
    router.navigate('/login', { state: router.location.state, replace: true });
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <div className="container page py-4 py-lg-5">
        <div className="row">
          <div className="col-md-6 col-lg-5 mx-auto">
            <div className="card border-0 shadow-sm">
              <div className="card-body p-4 p-lg-5">
                <h2 className="mb-1">{t('account.register.title')}</h2>
                <p className="text-muted mb-4">{t('account.register.intro')}</p>
                <RegisterForm onDone={this.done} onSwitch={this.switchToLogin} />
                <p className="text-muted small text-center mt-3 mb-0">
                  {t('account.register.browsing')} <Link to="/museums">{t('booking.my.explore')}</Link>
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

export const Register = withRouter(withI18n(RegisterBase));
