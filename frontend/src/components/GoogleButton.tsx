import * as React from 'react';
import { AuthResult, googleLogin } from '../api/auth2';
import { errorMessage } from '../api/client';
import { withI18n, WithI18nProps } from '../i18n';

/* Minimal typings for Google Identity Services (https://accounts.google.com/gsi/client). */
interface GsiCredentialResponse {
  credential: string;
}

interface GsiButtonOptions {
  type?: 'standard' | 'icon';
  theme?: 'outline' | 'filled_blue' | 'filled_black';
  size?: 'large' | 'medium' | 'small';
  text?: 'signin_with' | 'signup_with' | 'continue_with' | 'signin';
  shape?: 'rectangular' | 'pill' | 'circle' | 'square';
  logo_alignment?: 'left' | 'center';
  width?: number;
  locale?: string;
}

interface GsiId {
  initialize: (config: { client_id: string; callback: (r: GsiCredentialResponse) => void; ux_mode?: 'popup'; cancel_on_tap_outside?: boolean }) => void;
  renderButton: (parent: HTMLElement, options: GsiButtonOptions) => void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GsiId } };
  }
}

const GSI_SRC = 'https://accounts.google.com/gsi/client';
let gsiPromise: Promise<GsiId> | null = null;

/** Load the Google Identity Services script once per page. */
function loadGsi(): Promise<GsiId> {
  if (window.google?.accounts?.id) return Promise.resolve(window.google.accounts.id);
  gsiPromise ??= new Promise<GsiId>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = GSI_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => (window.google?.accounts?.id ? resolve(window.google.accounts.id) : reject(new Error('gsi')));
    script.onerror = () => {
      gsiPromise = null;
      script.remove();
      reject(new Error('gsi'));
    };
    document.head.appendChild(script);
  });
  return gsiPromise;
}

interface GoogleButtonProps extends WithI18nProps {
  clientId: string;
  /** Google's wording on the button. */
  text?: 'signin_with' | 'signup_with' | 'continue_with';
  /** Tokens or a two-step challenge from POST /auth/google/. */
  onResult: (result: AuthResult) => void;
  onError: (message: string) => void;
}

interface GoogleButtonState {
  status: 'loading' | 'ready' | 'failed';
  busy: boolean;
}

/** Google's official "Sign in with Google" button; posts the ID token to the backend. */
class GoogleButton extends React.Component<GoogleButtonProps, GoogleButtonState> {
  public state: GoogleButtonState = { status: 'loading', busy: false };

  private box = React.createRef<HTMLDivElement>();
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.renderGoogle();
  }

  public componentDidUpdate(prev: GoogleButtonProps): void {
    if (prev.clientId !== this.props.clientId || prev.i18n.lang !== this.props.i18n.lang || prev.text !== this.props.text) {
      this.renderGoogle();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private renderGoogle(): void {
    loadGsi()
      .then((gsi) => {
        const el = this.box.current;
        if (!this.mounted || !el) return;
        // initialize() is global; the latest mounted button owns the callback.
        gsi.initialize({ client_id: this.props.clientId, callback: this.onCredential, ux_mode: 'popup', cancel_on_tap_outside: true });
        el.innerHTML = '';
        const width = Math.max(200, Math.min(400, Math.floor(el.parentElement?.clientWidth ?? el.clientWidth ?? 320)));
        gsi.renderButton(el, {
          type: 'standard',
          theme: 'outline',
          size: 'large',
          shape: 'rectangular',
          logo_alignment: 'center',
          text: this.props.text ?? 'continue_with',
          width,
          locale: this.props.i18n.lang,
        });
        this.setState({ status: 'ready' });
      })
      .catch(() => this.mounted && this.setState({ status: 'failed' }));
  }

  private onCredential = async (response: GsiCredentialResponse): Promise<void> => {
    const { t } = this.props.i18n;
    this.setState({ busy: true });
    try {
      const result = await googleLogin(response.credential);
      this.props.onResult(result);
    } catch (err) {
      this.props.onError(errorMessage(err, t('auth2.google.failed')));
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { status, busy } = this.state;
    return (
      <div className="position-relative" style={{ minHeight: 44 }}>
        <div ref={this.box} className="d-flex justify-content-center" aria-busy={busy} />
        {status === 'loading' && (
          <div className="text-center text-muted small py-2">
            <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />
            {t('auth2.google.loading')}
          </div>
        )}
        {status === 'failed' && (
          <div className="text-center text-muted small py-2">
            <i className="bi bi-google me-1" aria-hidden="true" />
            {t('auth2.google.unavailable')}
          </div>
        )}
        {busy && (
          <div className="text-center small text-muted mt-1" role="status">
            <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />
            {t('auth2.google.signingIn')}
          </div>
        )}
      </div>
    );
  }
}

export default withI18n(GoogleButton);
