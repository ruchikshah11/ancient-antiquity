import * as React from 'react';
import { withI18n, WithI18nProps } from '../i18n';

/** Chrome/Edge/Android event fired when the site can be installed (not in the TS DOM lib). */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

const DISMISS_KEY = 'aa_install_dismissed';

function wasDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1';
  } catch {
    return false;
  }
}

function isStandalone(): boolean {
  const nav = navigator as Navigator & { standalone?: boolean };
  return window.matchMedia?.('(display-mode: standalone)').matches || nav.standalone === true;
}

function isIos(): boolean {
  const ua = navigator.userAgent;
  // iPadOS 13+ reports itself as a Mac; touch points tell it apart.
  return /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
}

interface State {
  mode: 'hidden' | 'prompt' | 'ios';
}

/**
 * Small dismissible banner offering to install the app (PWA).
 * Chrome/Edge/Android: uses the deferred `beforeinstallprompt` event. iOS Safari: shows the Share -> Add to
 * Home Screen hint. Hidden once installed or dismissed (dismissal remembered in localStorage).
 */
class InstallPromptBase extends React.Component<WithI18nProps, State> {
  public state: State = { mode: 'hidden' };

  private deferred: BeforeInstallPromptEvent | null = null;

  public componentDidMount(): void {
    if (isStandalone() || wasDismissed()) return;
    window.addEventListener('beforeinstallprompt', this.onBeforeInstall);
    window.addEventListener('appinstalled', this.onInstalled);
    if (isIos()) this.setState({ mode: 'ios' });
  }

  public componentWillUnmount(): void {
    window.removeEventListener('beforeinstallprompt', this.onBeforeInstall);
    window.removeEventListener('appinstalled', this.onInstalled);
  }

  private onBeforeInstall = (e: Event): void => {
    e.preventDefault(); // keep the browser's mini-infobar away; we show our own banner
    this.deferred = e as BeforeInstallPromptEvent;
    this.setState({ mode: 'prompt' });
  };

  private onInstalled = (): void => {
    this.deferred = null;
    this.setState({ mode: 'hidden' });
  };

  private install = async (): Promise<void> => {
    const event = this.deferred;
    if (!event) return;
    this.deferred = null;
    await event.prompt();
    const choice = await event.userChoice.catch(() => ({ outcome: 'dismissed' as const }));
    if (choice.outcome === 'dismissed') this.dismiss();
    else this.setState({ mode: 'hidden' });
  };

  private dismiss = (): void => {
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      /* storage unavailable: hide for this visit only */
    }
    this.setState({ mode: 'hidden' });
  };

  public render(): React.ReactNode {
    const { mode } = this.state;
    if (mode === 'hidden') return null;
    const { t } = this.props.i18n;
    return (
      <div className="position-fixed bottom-0 end-0 p-3" style={{ zIndex: 1080, maxWidth: '100%' }}>
        <div className="toast show shadow" role="status" aria-live="polite" data-testid="install-prompt">
          <div className="toast-header">
            <img src="/icon-192.png" alt="" width={20} height={20} className="rounded me-2" />
            <strong className="me-auto">{t('platform.install.title')}</strong>
            <button type="button" className="btn-close" aria-label={t('platform.install.close')} onClick={this.dismiss} />
          </div>
          <div className="toast-body">
            {mode === 'ios' ? (
              <p className="mb-0 small">
                <i className="bi bi-box-arrow-up me-1" aria-hidden="true" />
                {t('platform.install.iosBody')}
              </p>
            ) : (
              <>
                <p className="mb-2 small">{t('platform.install.body')}</p>
                <div className="d-flex gap-2">
                  <button type="button" className="btn btn-primary btn-sm" onClick={this.install}>
                    <i className="bi bi-download me-1" aria-hidden="true" />
                    {t('platform.install.button')}
                  </button>
                  <button type="button" className="btn btn-outline-secondary btn-sm" onClick={this.dismiss}>
                    {t('platform.install.dismiss')}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }
}

const InstallPrompt = withI18n(InstallPromptBase);
export default InstallPrompt;
