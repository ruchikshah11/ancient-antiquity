import * as React from 'react';
import {
  deletePushSubscription,
  getPushPublicKey,
  getServiceWorker,
  pushSupported,
  savePushSubscription,
  urlBase64ToUint8Array,
} from '../api/platform';
import { withAuth, WithAuthProps } from '../context/AuthContext';
import { withI18n, WithI18nProps } from '../i18n';

interface OwnProps {
  className?: string;
}

type Props = OwnProps & WithAuthProps & WithI18nProps;

interface State {
  /** hidden: push unsupported, not configured on the server, or not signed in. */
  status: 'loading' | 'hidden' | 'on' | 'off' | 'denied';
  busy: boolean;
  error: boolean;
}

/**
 * "Remind me the day before" switch: subscribes this browser to web push (VAPID) so the daily
 * send_visit_reminders job can notify it. Renders nothing where push is unavailable.
 * Usage: <ReminderSettings className="mt-3" /> (e.g. on the Ticket page).
 */
class ReminderSettingsBase extends React.Component<Props, State> {
  public state: State = { status: 'loading', busy: false, error: false };

  private publicKey: string | null = null;

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    void this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private set(state: Partial<State>): void {
    if (this.mounted) this.setState(state as State);
  }

  private async load(): Promise<void> {
    if (!this.props.auth.user || !pushSupported()) {
      this.set({ status: 'hidden' });
      return;
    }
    try {
      const { public_key } = await getPushPublicKey();
      this.publicKey = public_key;
      if (!public_key) {
        this.set({ status: 'hidden' });
        return;
      }
      if (Notification.permission === 'denied') {
        this.set({ status: 'denied' });
        return;
      }
      const reg = await navigator.serviceWorker.getRegistration('/');
      const sub = reg ? await reg.pushManager.getSubscription() : null;
      this.set({ status: sub ? 'on' : 'off' });
    } catch {
      this.set({ status: 'hidden' });
    }
  }

  private toggle = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const enable = e.target.checked;
    this.set({ busy: true, error: false });
    try {
      if (enable) await this.subscribe();
      else await this.unsubscribe();
    } catch {
      this.set({ error: true });
    } finally {
      this.set({ busy: false });
    }
  };

  private async subscribe(): Promise<void> {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      this.set({ status: permission === 'denied' ? 'denied' : 'off' });
      return;
    }
    const reg = await getServiceWorker();
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(this.publicKey ?? ''),
      });
    }
    await savePushSubscription(sub.toJSON());
    this.set({ status: 'on' });
  }

  private async unsubscribe(): Promise<void> {
    const reg = await navigator.serviceWorker.getRegistration('/');
    const sub = reg ? await reg.pushManager.getSubscription() : null;
    if (sub) {
      await deletePushSubscription(sub.endpoint);
      await sub.unsubscribe();
    }
    this.set({ status: 'off' });
  }

  public render(): React.ReactNode {
    const { status, busy, error } = this.state;
    if (status === 'loading' || status === 'hidden') return null;
    const { t } = this.props.i18n;
    const on = status === 'on';
    return (
      <div className={`card border-0 shadow-sm ${this.props.className ?? ''}`} data-testid="reminder-settings">
        <div className="card-body">
          <h3 className="h6 mb-2">
            <i className={`bi ${on ? 'bi-bell-fill text-primary' : 'bi-bell'} me-2`} aria-hidden="true" />
            {t('platform.reminder.title')}
          </h3>
          <div className="form-check form-switch">
            <input
              className="form-check-input"
              type="checkbox"
              role="switch"
              id="aa-reminder-toggle"
              checked={on}
              disabled={busy || status === 'denied'}
              onChange={this.toggle}
            />
            <label className="form-check-label" htmlFor="aa-reminder-toggle">
              {t('platform.reminder.toggle')}
            </label>
          </div>
          <p className="small text-muted mb-0 mt-1">
            {status === 'denied' ? (
              <>
                <i className="bi bi-bell-slash me-1" aria-hidden="true" />
                {t('platform.reminder.denied')}
              </>
            ) : (
              t(on ? 'platform.reminder.on' : 'platform.reminder.help')
            )}
          </p>
          {error && <div className="alert alert-danger small py-2 mt-2 mb-0">{t('platform.reminder.error')}</div>}
        </div>
      </div>
    );
  }
}

const ReminderSettings = withAuth(withI18n(ReminderSettingsBase));
export default ReminderSettings;
