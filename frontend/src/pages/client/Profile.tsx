import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { Link } from 'react-router-dom';
import {
  AuthUser,
  twoFactorBackupCodes,
  twoFactorDisable,
  twoFactorEnable,
  twoFactorSetup,
  TwoFactorStatus,
  twoFactorStatus,
} from '../../api/auth2';
import { api, errorMessage } from '../../api/client';
import { fetchCurrentMembership, Membership } from '../../api/memberships';
import type { User } from '../../api/types';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate } from '../../utils/format';
import { offerToSavePassword } from '../../utils/savePassword';

type ProfileProps = WithAuthProps & WithI18nProps;

interface Message {
  kind: 'success' | 'error';
  text: string;
}

interface ProfileState {
  form: { first_name: string; last_name: string; phone: string };
  pw: { old_password: string; new_password: string };
  msg: Message | null;
  pwMsg: Message | null;
}

type TwoFactorSectionProps = WithAuthProps & WithI18nProps;

interface TwoFactorSectionState {
  status: TwoFactorStatus | null;
  setup: { secret: string; otpauth_uri: string } | null;
  code: string;
  backupCodes: string[] | null;
  pending: 'disable' | 'regenerate' | null;
  msg: Message | null;
  busy: boolean;
  copied: boolean;
}

/** Staff/admin only: authenticator-app two-step verification with backup codes. */
class TwoFactorSectionBase extends React.Component<TwoFactorSectionProps, TwoFactorSectionState> {
  public state: TwoFactorSectionState = {
    status: null,
    setup: null,
    code: '',
    backupCodes: null,
    pending: null,
    msg: null,
    busy: false,
    copied: false,
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private load(): void {
    twoFactorStatus()
      .then((status) => this.mounted && this.setState({ status }))
      .catch((err) => this.mounted && this.setState({ msg: { kind: 'error', text: errorMessage(err) } }));
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.setState({ busy: true, msg: null });
    try {
      await action();
    } catch (err) {
      if (this.mounted) this.setState({ msg: { kind: 'error', text: errorMessage(err) }, code: '' });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  }

  private start = (): Promise<void> =>
    this.run(async () => {
      const setup = await twoFactorSetup();
      if (this.mounted) this.setState({ setup, code: '', backupCodes: null });
    });

  private enable = (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    return this.run(async () => {
      const r = await twoFactorEnable(this.state.code.trim());
      this.props.auth.setUser(r.user);
      if (this.mounted) {
        this.setState({ setup: null, code: '', backupCodes: r.backup_codes, msg: { kind: 'success', text: this.props.i18n.t('auth2.tfa.enabledMsg') } });
        this.load();
      }
    });
  };

  private confirmPending = (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { t } = this.props.i18n;
    return this.run(async () => {
      if (this.state.pending === 'disable') {
        const r = await twoFactorDisable(this.state.code.trim());
        this.props.auth.setUser(r.user);
        if (this.mounted) this.setState({ pending: null, code: '', backupCodes: null, msg: { kind: 'success', text: t('auth2.tfa.disabledMsg') } });
      } else {
        const r = await twoFactorBackupCodes(this.state.code.trim());
        if (this.mounted) this.setState({ pending: null, code: '', backupCodes: r.backup_codes, msg: { kind: 'success', text: t('auth2.tfa.regeneratedMsg') } });
      }
      this.load();
    });
  };

  private copyCodes = (): void => {
    const codes = this.state.backupCodes;
    if (!codes || !navigator.clipboard) return;
    navigator.clipboard.writeText(codes.join('\n')).then(
      () => this.mounted && this.setState({ copied: true }),
      () => undefined,
    );
  };

  private downloadCodes = (): void => {
    const codes = this.state.backupCodes;
    if (!codes) return;
    const text = `Ancient Antiquity backup codes (${this.props.auth.user?.email ?? ''})\nEach code works once.\n\n${codes.join('\n')}\n`;
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ancient-antiquity-backup-codes.txt';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  private codeInput(id: string): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <>
        <label htmlFor={id} className="form-label">{t('auth2.tfa.codeLabel')}</label>
        <input
          id={id}
          className="form-control"
          style={{ maxWidth: 220, letterSpacing: '0.2em' }}
          value={this.state.code}
          onChange={(e) => this.setState({ code: e.target.value.slice(0, 12) })}
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          autoFocus
        />
      </>
    );
  }

  private renderBackupCodes(): React.ReactNode {
    const { t } = this.props.i18n;
    const { backupCodes, copied } = this.state;
    if (!backupCodes) return null;
    return (
      <div className="border rounded p-3 bg-light mb-3">
        <h4 className="h6"><i className="bi bi-key me-2" aria-hidden="true" />{t('auth2.tfa.backupTitle')}</h4>
        <p className="small text-muted">{t('auth2.tfa.backupIntro')}</p>
        <div className="row row-cols-2 row-cols-sm-5 g-2 mb-3 font-monospace">
          {backupCodes.map((c) => <div key={c} className="col"><code className="text-dark">{c}</code></div>)}
        </div>
        <div className="d-flex flex-wrap gap-2">
          <button type="button" className="btn btn-sm btn-outline-primary" onClick={this.copyCodes}>
            <i className="bi bi-clipboard me-1" aria-hidden="true" />{copied ? t('auth2.tfa.copied') : t('auth2.tfa.copy')}
          </button>
          <button type="button" className="btn btn-sm btn-outline-primary" onClick={this.downloadCodes}>
            <i className="bi bi-download me-1" aria-hidden="true" />{t('auth2.tfa.download')}
          </button>
          <button type="button" className="btn btn-sm btn-link" onClick={() => this.setState({ backupCodes: null, copied: false })}>{t('auth2.tfa.savedThem')}</button>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { status, setup, pending, msg, busy } = this.state;
    const alertClass = (m: Message): string => `alert alert-${m.kind === 'error' ? 'danger' : 'success'}`;
    return (
      <section className="card border-0 shadow-sm mt-4" aria-labelledby="tfa-title">
        <div className="card-body p-4">
          <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
            <h3 id="tfa-title" className="h4 mb-0">
              <i className="bi bi-shield-check me-2 text-primary" aria-hidden="true" />
              {t('auth2.tfa.title')}
            </h3>
            {status && (
              <span className={`badge ${status.enabled ? 'bg-success' : 'bg-secondary'}`}>
                {status.enabled ? t('auth2.tfa.on') : t('auth2.tfa.off')}
              </span>
            )}
          </div>
          <p className="text-muted small">{t('auth2.tfa.intro')}</p>
          {msg && <div className={alertClass(msg)}>{msg.text}</div>}
          {this.renderBackupCodes()}

          {status === null ? (
            <div className="text-muted small"><span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />{t('auth2.wait')}</div>
          ) : status.enabled ? (
            <>
              <p className="mb-3 small">{t('auth2.tfa.backupLeft', { n: status.backup_codes_left })}</p>
              {pending ? (
                <form onSubmit={this.confirmPending} className="mb-0">
                  <p className="small mb-2">{pending === 'disable' ? t('auth2.tfa.disableHelp') : t('auth2.tfa.regenerateHelp')}</p>
                  <div className="mb-3">{this.codeInput('tfa-confirm')}</div>
                  <div className="d-flex gap-2">
                    <button className={`btn ${pending === 'disable' ? 'btn-danger' : 'btn-primary'}`} disabled={busy}>
                      {pending === 'disable' ? t('auth2.tfa.disable') : t('auth2.tfa.regenerate')}
                    </button>
                    <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ pending: null, code: '' })}>{t('auth2.cancel')}</button>
                  </div>
                </form>
              ) : (
                <div className="d-flex flex-wrap gap-2">
                  <button type="button" className="btn btn-outline-primary" onClick={() => this.setState({ pending: 'regenerate', code: '', msg: null })}>
                    <i className="bi bi-arrow-repeat me-1" aria-hidden="true" />{t('auth2.tfa.regenerate')}
                  </button>
                  <button type="button" className="btn btn-outline-danger" onClick={() => this.setState({ pending: 'disable', code: '', msg: null })}>
                    {t('auth2.tfa.disable')}
                  </button>
                </div>
              )}
            </>
          ) : setup ? (
            <form onSubmit={this.enable}>
              <ol className="small ps-3">
                <li>{t('auth2.tfa.step1')}</li>
                <li>{t('auth2.tfa.step2')}</li>
                <li>{t('auth2.tfa.step3')}</li>
              </ol>
              <div className="d-flex flex-wrap align-items-center gap-4 mb-3">
                <div className="bg-white p-2 border rounded">
                  <QRCodeSVG value={setup.otpauth_uri} size={168} />
                </div>
                <div className="small">
                  <div className="text-muted mb-1">{t('auth2.tfa.manualKey')}</div>
                  <code className="d-block text-break user-select-all fs-6">{setup.secret.replace(/(.{4})/g, '$1 ').trim()}</code>
                </div>
              </div>
              <div className="mb-3">{this.codeInput('tfa-enable')}</div>
              <div className="d-flex gap-2">
                <button className="btn btn-accent" disabled={busy || this.state.code.trim().length < 6}>{t('auth2.tfa.turnOn')}</button>
                <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ setup: null, code: '' })}>{t('auth2.cancel')}</button>
              </div>
            </form>
          ) : (
            <button type="button" className="btn btn-accent" disabled={busy} onClick={this.start}>
              <i className="bi bi-shield-lock me-1" aria-hidden="true" />{t('auth2.tfa.setUp')}
            </button>
          )}
        </div>
      </section>
    );
  }
}

const TwoFactorSection = withAuth(withI18n(TwoFactorSectionBase));

type TwoFactorSetupBannerProps = WithAuthProps & WithI18nProps;

/**
 * Reminder for staff/admins who must turn on two-step verification (STAFF_2FA_REQUIRED).
 * Renders nothing otherwise; meant for the admin layout (links to /profile).
 */
class TwoFactorSetupBannerBase extends React.Component<TwoFactorSetupBannerProps> {
  public render(): React.ReactNode {
    const user = this.props.auth.user as AuthUser | null;
    const { t } = this.props.i18n;
    if (!user?.two_factor_setup_required) return null;
    return (
      <div className="alert alert-warning d-flex align-items-center gap-2 flex-wrap" role="alert">
        <i className="bi bi-shield-exclamation fs-5" aria-hidden="true" />
        <span className="flex-grow-1">{t('auth2.tfa.banner')}</span>
        <Link to="/profile#two-step" className="btn btn-sm btn-warning">{t('auth2.tfa.setUp')}</Link>
      </div>
    );
  }
}

export const TwoFactorSetupBanner = withAuth(withI18n(TwoFactorSetupBannerBase));

interface HeritageCardSectionState {
  /** undefined while loading; null when the visitor has no card valid today. */
  card: Membership | null | undefined;
}

/** The visitor's Heritage Card valid today, or a prompt to get one. */
class HeritageCardSectionBase extends React.Component<WithI18nProps, HeritageCardSectionState> {
  public state: HeritageCardSectionState = { card: undefined };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    fetchCurrentMembership()
      .then((card) => this.mounted && this.setState({ card }))
      .catch(() => this.mounted && this.setState({ card: null }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public render(): React.ReactNode {
    const { card } = this.state;
    const { t } = this.props.i18n;
    if (card === undefined) return null;
    return (
      <section className="card border-0 shadow-sm mb-4" aria-labelledby="heritage-card-title">
        <div className="card-body p-4 d-flex flex-wrap align-items-center gap-3">
          <span className="addon-icon fs-4 flex-shrink-0" aria-hidden="true"><i className="bi bi-award" /></span>
          <div className="flex-grow-1">
            <h3 id="heritage-card-title" className="h5 mb-1">{t('shop.profile.cardTitle')}</h3>
            {card ? (
              <div className="small">
                <strong>{card.plan_name}</strong> · <span className="ref">{card.card_number}</span>
                {card.ends_on && <> · {t('shop.profile.validTill', { date: formatDate(card.ends_on) })}</>}
              </div>
            ) : (
              <div className="small text-muted">{t('shop.profile.prompt')}</div>
            )}
          </div>
          <Link to="/membership" className={card ? 'btn btn-outline-primary btn-sm' : 'btn btn-accent btn-sm'}>
            {card ? t('shop.profile.view') : t('shop.profile.get')}
          </Link>
        </div>
      </section>
    );
  }
}

const HeritageCardSection = withI18n(HeritageCardSectionBase);

class Profile extends React.Component<ProfileProps, ProfileState> {
  public state: ProfileState = {
    form: { first_name: this.props.auth.user!.first_name, last_name: this.props.auth.user!.last_name, phone: this.props.auth.user!.phone },
    pw: { old_password: '', new_password: '' },
    msg: null,
    pwMsg: null,
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private save = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    try {
      const { data } = await api.patch<User>('/auth/me/', this.state.form);
      this.props.auth.setUser(data);
      if (this.mounted) this.setState({ msg: { kind: 'success', text: this.props.i18n.t('account.profile.updated') } });
    } catch (err) {
      if (this.mounted) this.setState({ msg: { kind: 'error', text: errorMessage(err) } });
    }
  };

  private changePassword = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    try {
      await api.post('/auth/change-password/', this.state.pw);
      offerToSavePassword(this.props.auth.user?.email ?? '', this.state.pw.new_password);
      if (this.mounted) this.setState({ pw: { old_password: '', new_password: '' }, pwMsg: { kind: 'success', text: this.props.i18n.t('account.profile.passwordChanged') } });
    } catch (err) {
      if (this.mounted) this.setState({ pwMsg: { kind: 'error', text: errorMessage(err) } });
    }
  };

  public render(): React.ReactNode {
    const { user } = this.props.auth;
    const { t } = this.props.i18n;
    const { form, pw, msg, pwMsg } = this.state;
    const alertClass = (m: Message): string => `alert alert-${m.kind === 'error' ? 'danger' : 'success'}`;
    return (
      <div className="container page py-4 py-lg-5" style={{ maxWidth: 720 }}>
        <h1 className="display-6 mb-4">{t('account.profile.title')}</h1>
        <TwoFactorSetupBanner />
        <HeritageCardSection />
        <form className="card border-0 shadow-sm" onSubmit={this.save}>
          <div className="card-body p-4">
            <h3 className="h4 mb-3">
              <i className="bi bi-person-circle me-2 text-primary" aria-hidden="true" />
              {t('account.profile.personal')}
            </h3>
            {msg && <div className={alertClass(msg)}>{msg.text}</div>}
            <div className="row g-3">
              <div className="col-12">
                <label htmlFor="em" className="form-label">{t('account.email')}</label>
                <input id="em" className="form-control" value={user!.email} disabled />
              </div>
              <div className="col-md-6">
                <label htmlFor="fn" className="form-label">{t('account.firstName')}</label>
                <input id="fn" className="form-control" value={form.first_name} onChange={(e) => this.setState({ form: { ...form, first_name: e.target.value } })} />
              </div>
              <div className="col-md-6">
                <label htmlFor="ln" className="form-label">{t('account.lastName')}</label>
                <input id="ln" className="form-control" value={form.last_name} onChange={(e) => this.setState({ form: { ...form, last_name: e.target.value } })} />
              </div>
              <div className="col-md-6">
                <label htmlFor="ph" className="form-label">{t('account.mobile')}</label>
                <input id="ph" className="form-control" value={form.phone} onChange={(e) => this.setState({ form: { ...form, phone: e.target.value } })} />
              </div>
              <div className="col-12">
                <button className="btn btn-accent">{t('account.profile.save')}</button>
              </div>
            </div>
          </div>
        </form>

        <form className="card border-0 shadow-sm mt-4" onSubmit={this.changePassword}>
          <div className="card-body p-4">
            <h3 className="h4 mb-3">
              <i className="bi bi-shield-lock me-2 text-primary" aria-hidden="true" />
              {t('account.profile.changePassword')}
            </h3>
            {pwMsg && <div className={alertClass(pwMsg)}>{pwMsg.text}</div>}
            <div className="row g-3">
              <div className="col-md-6">
                <label htmlFor="op" className="form-label">{t('account.profile.currentPassword')}</label>
                <input id="op" name="current-password" type="password" autoComplete="current-password" className="form-control" value={pw.old_password} onChange={(e) => this.setState({ pw: { ...pw, old_password: e.target.value } })} required />
              </div>
              <div className="col-md-6">
                <label htmlFor="np" className="form-label">{t('account.newPassword')}</label>
                <input id="np" name="new-password" type="password" autoComplete="new-password" className="form-control" value={pw.new_password} onChange={(e) => this.setState({ pw: { ...pw, new_password: e.target.value } })} required minLength={8} />
              </div>
              <div className="col-12">
                <button className="btn btn-outline-primary">{t('account.profile.updatePassword')}</button>
              </div>
            </div>
          </div>
        </form>

        {user!.is_panel_user && (
          <div id="two-step">
            <TwoFactorSection />
          </div>
        )}
      </div>
    );
  }
}

export default withAuth(withI18n(Profile));
