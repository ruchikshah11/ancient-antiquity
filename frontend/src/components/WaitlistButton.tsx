import * as React from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { joinWaitlist, leaveWaitlist, myWaitlist, WAITLIST_CHANNELS } from '../api/events';
import type { WaitlistChannel, WaitlistEntry, WaitlistRequest } from '../api/events';
import { withAuth, WithAuthProps } from '../context/AuthContext';
import { withI18n, WithI18nProps } from '../i18n';
import { formatDate, formatTime } from '../utils/format';
import AuthModal from './AuthModal';

/*
 * "Notify me when seats free up" for a sold-out entry slot or event session.
 * Seats are not held: waiting visitors are told in sign-up order when a booking is cancelled or expires.
 */

export type WaitlistTarget = { museum: string; slot: number; visit_date: string } | { event_session: number };

const MAX_PARTY = 20;
let nextId = 0;

interface WaitlistButtonProps extends WithAuthProps, WithI18nProps {
  target: WaitlistTarget;
  /** What the visitor is waiting for, read out to screen readers ("Red Fort, 24 Oct 10:00 AM"). */
  label: string;
  className?: string;
}

interface WaitlistButtonState {
  open: boolean;
  quantity: number;
  channels: WaitlistChannel[];
  busy: boolean;
  error: string;
  entry: WaitlistEntry | null;
  authOpen: boolean;
}

class WaitlistButtonBase extends React.Component<WaitlistButtonProps, WaitlistButtonState> {
  public state: WaitlistButtonState = {
    open: false,
    quantity: 1,
    channels: ['email', 'sms'],
    busy: false,
    error: '',
    entry: null,
    authOpen: false,
  };

  private mounted = false;
  private uid = `wl${++nextId}`;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private toggleChannel(c: WaitlistChannel): void {
    this.setState((s) => ({ channels: s.channels.includes(c) ? s.channels.filter((x) => x !== c) : [...s.channels, c] }));
  }

  private submit = (): void => {
    if (!this.props.auth.user) this.setState({ authOpen: true });
    else this.join();
  };

  private join = async (): Promise<void> => {
    const { quantity, channels } = this.state;
    this.setState({ busy: true, error: '', authOpen: false });
    try {
      const body: WaitlistRequest = { ...this.props.target, quantity, notify_channels: channels };
      const { data } = await joinWaitlist(body);
      if (this.mounted) this.setState({ entry: data, open: false });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  private leave = async (): Promise<void> => {
    const { entry } = this.state;
    if (!entry) return;
    this.setState({ busy: true, error: '' });
    try {
      await leaveWaitlist(entry.id);
      if (this.mounted) this.setState({ entry: null });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { label, className } = this.props;
    const { open, quantity, channels, busy, error, entry, authOpen } = this.state;

    if (entry)
      return (
        <div className={`small text-success ${className ?? ''}`} role="status">
          <i className="bi bi-bell-fill me-1" aria-hidden="true" />
          {t('events.waitlist.joined', { n: entry.quantity })}{' '}
          <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={this.leave} disabled={busy}>
            {t('events.waitlist.leave')}
          </button>
        </div>
      );

    return (
      <div className={className}>
        <button
          type="button"
          className="btn btn-link btn-sm p-0 text-decoration-none"
          aria-expanded={open}
          aria-label={t('events.waitlist.buttonAria', { what: label })}
          onClick={() => this.setState({ open: !open, error: '' })}
        >
          <i className="bi bi-bell me-1" aria-hidden="true" />
          {t('events.waitlist.button')}
        </button>
        {open && (
          <div className="border rounded p-2 mt-1 bg-light small">
            <div className="d-flex align-items-center justify-content-between gap-2 mb-2">
              <span>{t('events.waitlist.people')}</span>
              <div className="input-group input-group-sm flex-nowrap" style={{ width: 100 }}>
                <button type="button" className="btn btn-outline-primary" aria-label={t('events.waitlist.fewer')} disabled={quantity <= 1} onClick={() => this.setState({ quantity: quantity - 1 })}>−</button>
                <span className="form-control text-center bg-white" aria-live="polite">{quantity}</span>
                <button type="button" className="btn btn-outline-primary" aria-label={t('events.waitlist.more')} disabled={quantity >= MAX_PARTY} onClick={() => this.setState({ quantity: quantity + 1 })}>+</button>
              </div>
            </div>
            <fieldset className="mb-2">
              <legend className="small fw-semibold mb-1" style={{ fontSize: 'inherit' }}>{t('events.waitlist.how')}</legend>
              <div className="d-flex flex-wrap gap-2">
                {WAITLIST_CHANNELS.map((c) => (
                  <div key={c} className="form-check form-check-inline m-0">
                    <input
                      id={`${this.uid}-${c}`}
                      type="checkbox"
                      className="form-check-input"
                      checked={channels.includes(c)}
                      onChange={() => this.toggleChannel(c)}
                    />
                    <label htmlFor={`${this.uid}-${c}`} className="form-check-label">{t(`events.waitlist.channel.${c}`)}</label>
                  </div>
                ))}
              </div>
            </fieldset>
            <p className="text-muted mb-2">{t('events.waitlist.note')}</p>
            {error && <div className="text-danger mb-2" role="alert">{error}</div>}
            <button type="button" className="btn btn-primary btn-sm w-100" onClick={this.submit} disabled={busy || channels.length === 0}>
              {busy ? t('events.waitlist.joining') : t('events.waitlist.join')}
            </button>
          </div>
        )}
        <AuthModal
          open={authOpen}
          title={t('events.waitlist.authTitle')}
          reason={t('events.waitlist.authReason')}
          onClose={() => this.setState({ authOpen: false })}
          onDone={this.join}
        />
      </div>
    );
  }
}

const WaitlistButton = withAuth(withI18n(WaitlistButtonBase));
export default WaitlistButton;

/* ---------------------------------------------------------------- MyWaitlist */

interface MyWaitlistState {
  entries: WaitlistEntry[] | null;
  busyId: number | null;
  error: string;
}

/** The signed-in visitor's open waitlist entries (for My bookings). Renders nothing when empty. */
class MyWaitlistBase extends React.Component<WithI18nProps, MyWaitlistState> {
  public state: MyWaitlistState = { entries: null, busyId: null, error: '' };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    myWaitlist()
      .then(({ data }) => this.mounted && this.setState({ entries: data }))
      .catch(() => this.mounted && this.setState({ entries: [] }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private leave = async (id: number): Promise<void> => {
    this.setState({ busyId: id, error: '' });
    try {
      await leaveWaitlist(id);
      if (this.mounted) this.setState((s) => ({ entries: (s.entries ?? []).filter((e) => e.id !== id) }));
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busyId: null });
    }
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { entries, busyId, error } = this.state;
    if (!entries || entries.length === 0) return null;
    return (
      <section className="mb-4" aria-labelledby="my-waitlist-title">
        <h2 id="my-waitlist-title" className="h5">
          <i className="bi bi-bell text-primary me-2" aria-hidden="true" />
          {t('events.waitlist.mine')}
        </h2>
        {error && <div className="alert alert-danger py-2">{error}</div>}
        <ul className="list-group">
          {entries.map((e) => {
            const link = e.event_slug ? `/events/${e.event_slug}?date=${e.visit_date}` : `/museums/${e.museum_slug}?date=${e.visit_date}`;
            return (
              <li key={e.id} className="list-group-item d-flex flex-wrap justify-content-between align-items-center gap-2">
                <div>
                  <Link to={link} className="fw-semibold">{e.event_title || e.museum_name}</Link>
                  <div className="small text-muted">
                    {e.event_title && <>{e.museum_name} · </>}
                    {formatDate(e.visit_date, { weekday: 'short', day: 'numeric', month: 'short' })}
                    {e.start_time && <>, {formatTime(e.start_time)}</>} · {t('events.waitlist.forPeople', { n: e.quantity })}
                  </div>
                </div>
                <div className="d-flex align-items-center gap-2">
                  <span className={`badge ${e.status === 'notified' ? 'bg-success' : 'bg-secondary'}`}>{t(`events.waitlist.status.${e.status}`)}</span>
                  {e.status === 'notified' && (
                    <Link to={link} className="btn btn-accent btn-sm">{t('events.waitlist.bookNow')}</Link>
                  )}
                  <button type="button" className="btn btn-outline-danger btn-sm" disabled={busyId === e.id} onClick={() => this.leave(e.id)}>
                    {t('events.waitlist.leave')}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    );
  }
}

export const MyWaitlist = withI18n(MyWaitlistBase);
