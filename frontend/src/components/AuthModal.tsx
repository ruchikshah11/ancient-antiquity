import * as React from 'react';
import type { User } from '../api/types';
import { withI18n, WithI18nProps } from '../i18n';
import { LoginForm, Prefill, RegisterForm } from '../pages/client/Auth';

type AuthTab = 'login' | 'register';

interface AuthModalProps extends WithI18nProps {
  open: boolean;
  title: string;
  reason?: string;
  prefill?: Prefill;
  initialTab?: AuthTab;
  onClose: () => void;
  onDone: (u: User) => void;
}

interface AuthModalState {
  tab: AuthTab;
}

/** Log in / sign up without leaving the page; the caller continues its action in onDone. */
class AuthModal extends React.Component<AuthModalProps, AuthModalState> {
  public state: AuthModalState = { tab: this.props.initialTab ?? 'register' };

  private listening = false;

  public componentDidMount(): void {
    if (this.props.open) this.attach();
  }

  public componentDidUpdate(prevProps: AuthModalProps): void {
    const { open, initialTab, onClose } = this.props;
    if (prevProps.open !== open || prevProps.initialTab !== initialTab || prevProps.onClose !== onClose) {
      this.detach();
      if (!open) return;
      this.setState({ tab: initialTab ?? 'register' });
      this.attach();
    }
  }

  public componentWillUnmount(): void {
    this.detach();
  }

  private onKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') this.props.onClose();
  };

  private attach(): void {
    if (this.listening) return;
    window.addEventListener('keydown', this.onKey);
    this.listening = true;
  }

  private detach(): void {
    if (!this.listening) return;
    window.removeEventListener('keydown', this.onKey);
    this.listening = false;
  }

  private setTab = (tab: AuthTab): void => {
    this.setState({ tab });
  };

  public render(): React.ReactNode {
    const { open, title, reason, prefill, onClose, onDone } = this.props;
    const { tab } = this.state;
    const { t } = this.props.i18n;
    if (!open) return null;

    return (
      <div className="modal show-react" role="dialog" aria-modal="true" aria-labelledby="auth-title" onClick={onClose}>
        <div className="modal-dialog modal-dialog-centered">
          <div className="modal-content border-0 shadow" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="auth-title" className="modal-title h4 mb-0">{title}</h3>
                {reason && <p className="small text-muted mt-1 mb-0">{reason}</p>}
              </div>
              <button type="button" className="btn-close" aria-label={t('common.close')} onClick={onClose} />
            </div>
            <div className="modal-body">
              <div className="nav nav-pills nav-fill mb-3" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === 'register'}
                  className={`nav-link ${tab === 'register' ? 'active' : ''}`}
                  onClick={() => this.setTab('register')}
                >
                  <i className="bi bi-person-plus me-1" aria-hidden="true" />
                  {t('common.auth.newVisitor')}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab === 'login'}
                  className={`nav-link ${tab === 'login' ? 'active' : ''}`}
                  onClick={() => this.setTab('login')}
                >
                  <i className="bi bi-box-arrow-in-right me-1" aria-hidden="true" />
                  {t('common.auth.haveAccount')}
                </button>
              </div>
              {tab === 'register' ? (
                <RegisterForm key="r" prefill={prefill} onDone={onDone} onSwitch={() => this.setTab('login')} />
              ) : (
                <LoginForm key="l" prefill={prefill} onDone={onDone} onSwitch={() => this.setTab('register')} />
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }
}

export default withI18n(AuthModal);
