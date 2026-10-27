import * as React from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../api/client';
import { requestPasswordReset } from '../../api/notifications';
import { withI18n, WithI18nProps } from '../../i18n';

interface ForgotPasswordState {
  email: string;
  sent: boolean;
  error: string;
  busy: boolean;
}

/** Ask for a password-reset link. Shows the same message whether or not the email is registered. */
class ForgotPassword extends React.Component<WithI18nProps, ForgotPasswordState> {
  public state: ForgotPasswordState = { email: '', sent: false, error: '', busy: false };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    this.setState({ busy: true, error: '' });
    try {
      await requestPasswordReset(this.state.email.trim());
      if (this.mounted) this.setState({ sent: true });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { email, sent, error, busy } = this.state;
    const { t } = this.props.i18n;
    return (
      <div className="container page py-4 py-lg-5">
        <div className="row">
          <div className="col-md-6 col-lg-5 mx-auto">
            <div className="card border-0 shadow-sm">
              <div className="card-body p-4 p-lg-5">
                <h2 className="mb-1">{t('account.forgot.title')}</h2>
                {sent ? (
                  <>
                    <div className="alert alert-success d-flex gap-2 mt-3" role="status">
                      <i className="bi bi-envelope" aria-hidden="true" />
                      <span>{t('account.forgot.sent')}</span>
                    </div>
                    <p className="text-muted small">
                      {t('account.forgot.notReceived')}{' '}
                      <button type="button" className="btn btn-link p-0 align-baseline small" onClick={() => this.setState({ sent: false })}>
                        {t('account.forgot.tryAgain')}
                      </button>
                      {t('account.forgot.tryAgainAfter')}
                    </p>
                    <Link to="/login" className="btn btn-outline-primary w-100">{t('account.backToLogin')}</Link>
                  </>
                ) : (
                  <form onSubmit={this.submit}>
                    <p className="text-muted mb-4">{t('account.forgot.intro')}</p>
                    {error && <div className="alert alert-danger">{error}</div>}
                    <div className="mb-4">
                      <label htmlFor="fp-email" className="form-label">{t('account.email')}</label>
                      <input
                        id="fp-email"
                        type="email"
                        className="form-control"
                        value={email}
                        onChange={(e) => this.setState({ email: e.target.value })}
                        required
                        autoComplete="email"
                        autoFocus
                      />
                    </div>
                    <button className="btn btn-accent btn-lg w-100" disabled={busy}>{busy ? t('account.sending') : t('account.forgot.submit')}</button>
                    <p className="text-muted small text-center mt-3 mb-0">
                      {t('account.forgot.remembered')} <Link to="/login">{t('account.login.submit')}</Link>
                    </p>
                  </form>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

export default withI18n(ForgotPassword);
