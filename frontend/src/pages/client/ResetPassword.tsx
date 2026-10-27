import * as React from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../api/client';
import { confirmPasswordReset } from '../../api/notifications';
import { withI18n, WithI18nProps } from '../../i18n';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

type ResetPasswordProps = WithRouterProps & WithI18nProps;

interface ResetPasswordState {
  password: string;
  confirm: string;
  done: boolean;
  error: string;
  busy: boolean;
}

/** Landing page of the emailed link /reset-password/:uid/:token. */
class ResetPassword extends React.Component<ResetPasswordProps, ResetPasswordState> {
  public state: ResetPasswordState = { password: '', confirm: '', done: false, error: '', busy: false };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { password, confirm } = this.state;
    if (password !== confirm) {
      this.setState({ error: this.props.i18n.t('account.reset.mismatchTwo') });
      return;
    }
    const { uid = '', token = '' } = this.props.router.params;
    this.setState({ busy: true, error: '' });
    try {
      await confirmPasswordReset({ uid, token, new_password: password });
      if (this.mounted) this.setState({ done: true });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { password, confirm, done, error, busy } = this.state;
    const mismatch = confirm.length > 0 && password !== confirm;
    const { t } = this.props.i18n;
    return (
      <div className="container page py-4 py-lg-5">
        <div className="row">
          <div className="col-md-6 col-lg-5 mx-auto">
            <div className="card border-0 shadow-sm">
              <div className="card-body p-4 p-lg-5">
                <h2 className="mb-1">{t('account.reset.title')}</h2>
                {done ? (
                  <>
                    <div className="alert alert-success d-flex gap-2 mt-3" role="status">
                      <i className="bi bi-check-circle-fill" aria-hidden="true" />
                      <span>{t('account.reset.done')}</span>
                    </div>
                    <Link to="/login" className="btn btn-accent btn-lg w-100">{t('account.login.submit')}</Link>
                  </>
                ) : (
                  <form onSubmit={this.submit}>
                    <p className="text-muted mb-4">{t('account.reset.intro')}</p>
                    {error && (
                      <div className="alert alert-danger">
                        {error}
                        {/invalid or has expired/i.test(error) && (
                          <> <Link to="/forgot-password" className="alert-link">{t('account.reset.newLink')}</Link>{t('account.reset.newLinkAfter')}</>
                        )}
                      </div>
                    )}
                    <div className="mb-3">
                      <label htmlFor="rp-pw" className="form-label">{t('account.newPassword')}</label>
                      <input
                        id="rp-pw"
                        type="password"
                        className="form-control"
                        value={password}
                        onChange={(e) => this.setState({ password: e.target.value })}
                        required
                        minLength={8}
                        autoComplete="new-password"
                        aria-describedby="rp-pw-help"
                        autoFocus
                      />
                      <div id="rp-pw-help" className="form-text">{t('account.passwordHelp')}</div>
                    </div>
                    <div className="mb-4">
                      <label htmlFor="rp-pw2" className="form-label">{t('account.reset.confirm')}</label>
                      <input
                        id="rp-pw2"
                        type="password"
                        className={`form-control${mismatch ? ' is-invalid' : ''}`}
                        value={confirm}
                        onChange={(e) => this.setState({ confirm: e.target.value })}
                        required
                        autoComplete="new-password"
                      />
                      {mismatch && <div className="invalid-feedback">{t('account.reset.mismatch')}</div>}
                    </div>
                    <button className="btn btn-accent btn-lg w-100" disabled={busy || mismatch}>
                      {busy ? t('account.saving') : t('account.reset.submit')}
                    </button>
                    <p className="text-muted small text-center mt-3 mb-0">
                      <Link to="/login">{t('account.backToLogin')}</Link>
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

export default withRouter(withI18n(ResetPassword));
