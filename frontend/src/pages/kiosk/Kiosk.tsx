import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { KioskMe, KioskSession, KioskSlot } from '../../api/partners';
import { openRazorpay, RazorpayOrder } from '../../api/razorpay';
import type { Booking } from '../../api/types';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { LANGS, withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatINR, formatTime } from '../../utils/format';

/*
 * Self-service kiosk for walk-in visitors. The device signs in once with a kiosk account, picks its place
 * (remembered on the device), then loops: tickets for today's current/next slot -> pay -> big QR ticket.
 * Any screen returns to the start after IDLE_SECONDS without a touch.
 */

const MUSEUM_KEY = 'aa_kiosk_museum';
const IDLE_SECONDS = 60;
const MAX_TICKETS = 20;
const BRAND_COLOR = '#0277bd';
const DEMO_METHODS: { id: string; icon: string }[] = [
  { id: 'upi', icon: 'bi-phone' },
  { id: 'card', icon: 'bi-credit-card' },
];

type Screen = 'tickets' | 'pay' | 'done' | 'settings';

function readMuseum(): string {
  try {
    return localStorage.getItem(MUSEUM_KEY) ?? '';
  } catch {
    return '';
  }
}

function storeMuseum(slug: string): void {
  try {
    if (slug) localStorage.setItem(MUSEUM_KEY, slug);
    else localStorage.removeItem(MUSEUM_KEY);
  } catch {
    /* storage unavailable: the place has to be picked again after a reload */
  }
}

interface Props extends WithAuthProps, WithI18nProps {}

interface State {
  me: KioskMe | null;
  meError: string;
  museum: string;
  session: KioskSession | null;
  screen: Screen;
  slotId: number | null;
  qty: Record<number, number>;
  booking: Booking | null;
  provider: 'razorpay' | 'mock' | null;
  busy: boolean;
  paying: boolean;
  error: string;
  idleLeft: number;
  // sign-in
  email: string;
  password: string;
  // unlock settings
  unlockPassword: string;
  unlocked: boolean;
}

class KioskBase extends React.Component<Props, State> {
  public state: State = {
    me: null, meError: '', museum: readMuseum(), session: null, screen: 'tickets', slotId: null, qty: {},
    booking: null, provider: null, busy: false, paying: false, error: '', idleLeft: IDLE_SECONDS,
    email: '', password: '', unlockPassword: '', unlocked: false,
  };

  private mounted = false;
  private tick: ReturnType<typeof setInterval> | undefined;
  private lastTouch = Date.now();
  private lastSessionLoad = 0;

  public componentDidMount(): void {
    this.mounted = true;
    document.addEventListener('pointerdown', this.touched, true);
    document.addEventListener('keydown', this.touched, true);
    this.tick = setInterval(this.onTick, 1000);
    if (this.isKiosk()) this.loadMe();
    api
      .get<{ provider: 'razorpay' | 'mock' }>('/payments/config/')
      .then((r) => this.mounted && this.setState({ provider: r.data.provider }))
      .catch(() => this.mounted && this.setState({ provider: 'mock' }));
  }

  public componentDidUpdate(prev: Props, prevState: State): void {
    if (prev.auth.user !== this.props.auth.user && this.isKiosk()) this.loadMe();
    if (prevState.museum !== this.state.museum) this.loadSession();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    document.removeEventListener('pointerdown', this.touched, true);
    document.removeEventListener('keydown', this.touched, true);
    clearInterval(this.tick);
  }

  private isKiosk(): boolean {
    return (this.props.auth.user?.role as string | undefined) === 'kiosk';
  }

  private touched = (): void => {
    this.lastTouch = Date.now();
    if (this.state.idleLeft !== IDLE_SECONDS) this.setState({ idleLeft: IDLE_SECONDS });
  };

  /** Idle reset plus a periodic refresh of seats left. */
  private onTick = (): void => {
    const { screen, paying, qty, booking, museum } = this.state;
    const idle = (Date.now() - this.lastTouch) / 1000;
    const dirty = screen !== 'tickets' || booking !== null || Object.values(qty).some((n) => n > 0);
    if (dirty && !paying) {
      const left = Math.max(0, Math.ceil(IDLE_SECONDS - idle));
      if (left !== this.state.idleLeft) this.setState({ idleLeft: left });
      if (left === 0) this.reset();
    }
    if (museum && screen === 'tickets' && Date.now() - this.lastSessionLoad > 60000) this.loadSession();
  };

  private loadMe(): void {
    api
      .get<KioskMe>('/kiosk/me/')
      .then((r) => {
        if (!this.mounted) return;
        const allowed = r.data.museums.map((m) => m.slug);
        let museum = this.state.museum;
        if (!allowed.includes(museum)) museum = allowed.length === 1 ? allowed[0] : '';
        storeMuseum(museum);
        this.setState({ me: r.data, meError: '', museum }, () => museum && this.loadSession());
      })
      .catch((err) => this.mounted && this.setState({ meError: errorMessage(err) }));
  }

  private loadSession(): void {
    const { museum } = this.state;
    if (!museum) return;
    this.lastSessionLoad = Date.now();
    api
      .get<KioskSession>('/kiosk/session/', { params: { museum } })
      .then((r) => {
        if (!this.mounted || this.state.museum !== museum) return;
        this.setState((s) => ({
          session: r.data,
          slotId: r.data.slots.some((x) => x.id === s.slotId && x.bookable)
            ? s.slotId
            : r.data.slots.find((x) => x.bookable)?.id ?? null,
        }));
      })
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  }

  /** Back to the start for the next visitor; an unpaid booking is cancelled so its seats free up at once. */
  private reset = (): void => {
    const { booking } = this.state;
    if (booking && booking.status === 'pending') api.post(`/bookings/${booking.reference}/cancel/`).catch(() => undefined);
    this.lastTouch = Date.now();
    this.setState({
      screen: 'tickets', qty: {}, booking: null, error: '', busy: false, paying: false, idleLeft: IDLE_SECONDS,
      unlocked: false, unlockPassword: '',
    });
    this.loadSession();
  };

  private step = (id: number, delta: number): void => {
    this.setState((s) => ({ qty: { ...s.qty, [id]: Math.max(0, (s.qty[id] ?? 0) + delta) } }));
  };

  private signIn = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    this.setState({ busy: true, error: '' });
    try {
      await this.props.auth.login(this.state.email, this.state.password);
      this.setState({ busy: false, password: '' });
    } catch (err) {
      this.setState({ busy: false, error: err instanceof Error && !('response' in err) ? err.message : errorMessage(err) });
    }
  };

  private startPayment = async (): Promise<void> => {
    const { session, slotId, qty } = this.state;
    if (!session || !slotId) return;
    this.setState({ busy: true, error: '' });
    try {
      const { data } = await api.post<Booking>('/kiosk/bookings/', {
        museum: session.museum.slug,
        slot: slotId,
        items: Object.entries(qty).filter(([, n]) => n > 0).map(([id, n]) => ({ ticket_type: Number(id), quantity: n })),
      });
      this.setState({ booking: data, busy: false, screen: data.status === 'pending' ? 'pay' : 'done' });
    } catch (err) {
      this.setState({ busy: false, error: errorMessage(err) });
      this.loadSession();
    }
  };

  private pay = async (method: string): Promise<void> => {
    const { booking } = this.state;
    if (!booking) return;
    const { t } = this.props.i18n;
    this.setState({ busy: true, paying: true, error: '' });
    try {
      const { data: order } = await api.post<RazorpayOrder | { provider: 'mock' }>(`/bookings/${booking.reference}/payment-order/`);
      let paid: Booking;
      if (order.provider === 'razorpay') {
        const result = await openRazorpay(order, BRAND_COLOR);
        if (!result) {
          this.setState({ busy: false, paying: false });
          return;
        }
        paid = (await api.post<Booking>(`/bookings/${booking.reference}/pay/`, result)).data;
      } else {
        paid = (await api.post<Booking>(`/bookings/${booking.reference}/pay/`, { method })).data;
      }
      this.lastTouch = Date.now();
      this.setState({ booking: paid, screen: 'done', busy: false, paying: false, idleLeft: IDLE_SECONDS });
    } catch (err) {
      this.lastTouch = Date.now();
      this.setState({ busy: false, paying: false, error: err instanceof Error && !('response' in err) ? err.message || t('partners.kiosk.payFailed') : errorMessage(err, t('partners.kiosk.payFailed')) });
    }
  };

  private unlock = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { t } = this.props.i18n;
    this.setState({ busy: true, error: '' });
    try {
      // Re-entering the kiosk account password proves a staff member is at the screen.
      await api.post('/auth/login/', { email: this.props.auth.user?.email, password: this.state.unlockPassword });
      this.setState({ unlocked: true, busy: false, unlockPassword: '' });
    } catch {
      this.setState({ busy: false, error: t('partners.kiosk.wrongPassword'), unlockPassword: '' });
    }
  };

  private chooseMuseum = (slug: string): void => {
    storeMuseum(slug);
    this.setState({ museum: slug, session: null, slotId: null, qty: {}, screen: 'tickets', unlocked: false });
  };

  private fullScreen = (): void => {
    const el = document.documentElement;
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => undefined);
    else el.requestFullscreen?.().catch(() => undefined);
  };

  private signOut = (): void => {
    storeMuseum('');
    this.props.auth.logout();
    this.setState({ me: null, museum: '', session: null, screen: 'tickets', unlocked: false, booking: null, qty: {} });
  };

  // --------------------------------------------------------------------------------------- render

  private renderHeader(): React.ReactNode {
    const { t, lang, setLang } = this.props.i18n;
    const { session, screen } = this.state;
    return (
      <header className="bg-navy text-white px-3 px-md-4 py-3 d-flex align-items-center gap-3 no-print">
        <i className="bi bi-bank fs-2" aria-hidden="true" />
        <div className="flex-grow-1 min-w-0">
          <div className="fs-4 fw-bold text-truncate">{session?.museum.name ?? t('partners.kiosk.title')}</div>
          <div className="small opacity-75">{t('partners.kiosk.subtitle')}</div>
        </div>
        <div className="btn-group" role="group" aria-label={t('partners.kiosk.language')}>
          {LANGS.map((l) => (
            <button key={l.value} type="button" className={`btn btn-lg ${lang === l.value ? 'btn-light' : 'btn-outline-light'}`} aria-pressed={lang === l.value} onClick={() => setLang(l.value)}>
              {l.label}
            </button>
          ))}
        </div>
        {this.isKiosk() && screen !== 'settings' && (
          <button type="button" className="btn btn-outline-light btn-lg" aria-label={t('partners.kiosk.settings')} onClick={() => this.setState({ screen: 'settings', error: '' })}>
            <i className="bi bi-gear" aria-hidden="true" />
          </button>
        )}
      </header>
    );
  }

  private renderSignIn(): React.ReactNode {
    const { t } = this.props.i18n;
    const { email, password, busy, error } = this.state;
    return (
      <form className="card border-0 shadow mx-auto my-5" style={{ maxWidth: 480 }} onSubmit={this.signIn}>
        <div className="card-body p-4">
          <h1 className="h3 mb-3"><i className="bi bi-tablet me-2" aria-hidden="true" />{t('partners.kiosk.signInTitle')}</h1>
          <p className="text-muted">{t('partners.kiosk.signInHint')}</p>
          {error && <div className="alert alert-danger" role="alert">{error}</div>}
          <label htmlFor="k-email" className="form-label">{t('partners.kiosk.email')}</label>
          <input id="k-email" type="email" className="form-control form-control-lg mb-3" required autoComplete="username" value={email} onChange={(e) => this.setState({ email: e.target.value })} />
          <label htmlFor="k-pass" className="form-label">{t('partners.kiosk.password')}</label>
          <input id="k-pass" type="password" className="form-control form-control-lg mb-4" required autoComplete="current-password" value={password} onChange={(e) => this.setState({ password: e.target.value })} />
          <button className="btn btn-accent btn-lg w-100" disabled={busy}>{busy ? t('partners.common.sending') : t('partners.kiosk.signIn')}</button>
        </div>
      </form>
    );
  }

  private renderPlacePicker(): React.ReactNode {
    const { t } = this.props.i18n;
    const { me } = this.state;
    if (!me) return null;
    return (
      <div className="container py-4">
        <h2 className="h3 mb-3">{t('partners.kiosk.pickPlace')}</h2>
        {me.museums.length === 0 ? (
          <div className="alert alert-warning fs-5">{t('partners.kiosk.noPlaces')}</div>
        ) : (
          <div className="row g-3">
            {me.museums.map((m) => (
              <div className="col-md-6" key={m.slug}>
                <button type="button" className={`btn btn-lg w-100 text-start py-4 ${this.state.museum === m.slug ? 'btn-primary' : 'btn-outline-primary'}`} onClick={() => this.chooseMuseum(m.slug)}>
                  <i className="bi bi-building me-2" aria-hidden="true" />
                  <strong>{m.name}</strong> <span className="opacity-75">· {m.city_name}</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  private renderSettings(): React.ReactNode {
    const { t } = this.props.i18n;
    const { unlocked, unlockPassword, busy, error, me } = this.state;
    return (
      <div className="container py-4" style={{ maxWidth: 720 }}>
        <button type="button" className="btn btn-link btn-lg px-0 mb-3" onClick={this.reset}>
          <i className="bi bi-arrow-left me-1" aria-hidden="true" />{t('partners.kiosk.back')}
        </button>
        {!unlocked ? (
          <form className="card border-0 shadow-sm" onSubmit={this.unlock}>
            <div className="card-body p-4">
              <h2 className="h4"><i className="bi bi-lock me-2" aria-hidden="true" />{t('partners.kiosk.staffOnly')}</h2>
              <p className="text-muted">{t('partners.kiosk.unlockHint')}</p>
              {error && <div className="alert alert-danger">{error}</div>}
              <label htmlFor="k-unlock" className="visually-hidden">{t('partners.kiosk.password')}</label>
              <input id="k-unlock" type="password" className="form-control form-control-lg mb-3" autoComplete="off" value={unlockPassword} onChange={(e) => this.setState({ unlockPassword: e.target.value })} />
              <button className="btn btn-primary btn-lg" disabled={busy || !unlockPassword}>{t('partners.kiosk.unlock')}</button>
            </div>
          </form>
        ) : (
          <div className="d-flex flex-column gap-3">
            <div className="text-muted">{me?.name}</div>
            {this.renderPlacePicker()}
            <div className="d-flex flex-wrap gap-2">
              <button type="button" className="btn btn-outline-primary btn-lg" onClick={this.fullScreen}>
                <i className="bi bi-fullscreen me-2" aria-hidden="true" />{t('partners.kiosk.fullScreen')}
              </button>
              <button type="button" className="btn btn-outline-danger btn-lg" onClick={this.signOut}>
                <i className="bi bi-box-arrow-right me-2" aria-hidden="true" />{t('partners.kiosk.signOut')}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  private renderTickets(): React.ReactNode {
    const { t } = this.props.i18n;
    const { session, slotId, qty, busy, error } = this.state;
    if (!session) {
      return <div className="d-flex justify-content-center py-5"><div className="spinner-border text-primary" role="status"><span className="visually-hidden">{t('common.loading')}</span></div></div>;
    }
    const slots = session.slots.filter((s) => s.bookable).slice(0, 4);
    const slot: KioskSlot | undefined = session.slots.find((s) => s.id === slotId);
    const count = Object.values(qty).reduce((a, b) => a + b, 0);
    const total = session.tickets.reduce((sum, tk) => sum + Number(tk.price) * (qty[tk.ticket_type] ?? 0), 0);
    const cap = Math.min(MAX_TICKETS, slot?.available ?? 0);

    if (session.closed || slots.length === 0) {
      return (
        <div className="container py-5 text-center">
          <i className="bi bi-clock display-1 text-muted" aria-hidden="true" />
          <h2 className="display-6 mt-3">{session.closed ? t('partners.kiosk.closedToday') : t('partners.kiosk.noSlots')}</h2>
          {session.closed_reason && <p className="fs-5 text-muted">{session.closed_reason}</p>}
        </div>
      );
    }

    return (
      <div className="container py-4">
        <h2 className="display-6 mb-1">{t('partners.kiosk.welcome')}</h2>
        <p className="fs-5 text-muted">{t('partners.kiosk.today', { date: formatDate(session.date, { weekday: 'long', day: 'numeric', month: 'long' }) })}</p>
        {error && <div className="alert alert-danger fs-5" role="alert">{error}</div>}

        <h3 className="h4 mt-4">{t('partners.kiosk.chooseSlot')}</h3>
        <div className="row g-3 mb-4">
          {slots.map((s) => (
            <div className="col-6 col-lg-3" key={s.id}>
              <button type="button" className={`btn btn-lg w-100 py-3 slot-btn ${slotId === s.id ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={slotId === s.id} onClick={() => this.setState({ slotId: s.id })}>
                <strong className="fs-4">{formatTime(s.start_time)}</strong>
                <small>{s.running ? t('partners.kiosk.runningNow') : t('partners.kiosk.startsAt', { time: formatTime(s.start_time) })} · {t('partners.kiosk.left', { n: s.available })}</small>
              </button>
            </div>
          ))}
        </div>

        <h3 className="h4">{t('partners.kiosk.chooseTickets')}</h3>
        <ul className="list-group mb-4">
          {session.tickets.map((tk) => (
            <li key={tk.ticket_type} className="list-group-item d-flex flex-wrap justify-content-between align-items-center gap-3 py-3">
              <div>
                <div className="fs-4 fw-semibold">{tk.name}</div>
                <div className="fs-5 text-muted">{Number(tk.price) === 0 ? t('partners.kiosk.free') : formatINR(tk.price)}</div>
              </div>
              <div className="d-flex align-items-center gap-3">
                <button type="button" className="btn btn-outline-primary btn-lg rounded-circle" style={{ width: 64, height: 64 }} aria-label={t('partners.common.fewer', { name: tk.name })} disabled={!qty[tk.ticket_type]} onClick={() => this.step(tk.ticket_type, -1)}>
                  <i className="bi bi-dash-lg fs-3" aria-hidden="true" />
                </button>
                <span className="fs-2 fw-bold text-center" style={{ minWidth: 48 }} aria-live="polite">{qty[tk.ticket_type] ?? 0}</span>
                <button type="button" className="btn btn-primary btn-lg rounded-circle" style={{ width: 64, height: 64 }} aria-label={t('partners.common.more', { name: tk.name })} disabled={count >= cap} onClick={() => this.step(tk.ticket_type, 1)}>
                  <i className="bi bi-plus-lg fs-3" aria-hidden="true" />
                </button>
              </div>
            </li>
          ))}
        </ul>

        <div className="d-flex flex-wrap justify-content-between align-items-center gap-3 border-top pt-3">
          <div className="fs-3 fw-bold">{t('partners.kiosk.total', { n: count })} {formatINR(total)}</div>
          <div className="d-flex gap-2">
            {count > 0 && <button type="button" className="btn btn-outline-secondary btn-lg px-4" onClick={this.reset}>{t('partners.kiosk.clear')}</button>}
            <button type="button" className="btn btn-accent btn-lg px-5 py-3 fs-4" disabled={busy || count === 0 || !slot} onClick={this.startPayment}>
              {busy ? t('partners.common.sending') : total === 0 ? t('partners.kiosk.getTickets') : t('partners.kiosk.pay', { amount: formatINR(total) })}
            </button>
          </div>
        </div>
      </div>
    );
  }

  private renderPay(): React.ReactNode {
    const { t } = this.props.i18n;
    const { booking, provider, busy, error, idleLeft } = this.state;
    if (!booking) return null;
    return (
      <div className="container py-5 text-center" style={{ maxWidth: 720 }}>
        <h2 className="display-6">{t('partners.kiosk.payTitle', { amount: formatINR(booking.total_amount) })}</h2>
        <p className="fs-5 text-muted">{booking.items.map((i) => `${i.quantity} × ${i.ticket_name}`).join(', ')} · {formatTime(booking.slot_start)}</p>
        {error && <div className="alert alert-danger fs-5" role="alert">{error}</div>}
        {provider === 'razorpay' ? (
          <button type="button" className="btn btn-accent btn-lg px-5 py-4 fs-3 my-3" disabled={busy} onClick={() => this.pay('upi')}>
            <i className="bi bi-phone me-2" aria-hidden="true" />{busy ? t('partners.kiosk.paying') : t('partners.kiosk.payNow')}
          </button>
        ) : (
          <>
            <div className="alert alert-info">{t('partners.kiosk.demo')}</div>
            <div className="row g-3 my-2">
              {DEMO_METHODS.map((m) => (
                <div className="col-6" key={m.id}>
                  <button type="button" className="btn btn-outline-primary btn-lg w-100 py-4 fs-4" disabled={busy} onClick={() => this.pay(m.id)}>
                    <i className={`bi ${m.icon} d-block display-6 mb-2`} aria-hidden="true" />
                    {t(`partners.kiosk.method.${m.id}`)}
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
        <p className="text-muted mt-3">{t('partners.kiosk.payHint')}</p>
        <button type="button" className="btn btn-link btn-lg" onClick={this.reset} disabled={busy && this.state.paying}>{t('partners.kiosk.cancel')}</button>
        {!this.state.paying && <div className="small text-muted">{t('partners.kiosk.resetIn', { n: idleLeft })}</div>}
      </div>
    );
  }

  private renderDone(): React.ReactNode {
    const { t } = this.props.i18n;
    const { booking, idleLeft } = this.state;
    if (!booking) return null;
    return (
      <div className="container py-4 text-center" style={{ maxWidth: 640 }}>
        <div className="alert alert-success fs-4 no-print"><i className="bi bi-check-circle-fill me-2" aria-hidden="true" />{t('partners.kiosk.thanks')}</div>
        <div className="card border-0 shadow">
          <div className="card-body p-4 d-flex flex-column align-items-center gap-2">
            <div className="text-muted small">ANCIENT ANTIQUITY · {t('partners.kiosk.ticketLabel').toUpperCase()}</div>
            <h2 className="h3 mb-0">{booking.museum_name}</h2>
            <div className="fs-5">{formatDate(booking.visit_date)} · {formatTime(booking.slot_start)} – {formatTime(booking.slot_end)}</div>
            <div className="bg-white p-3 rounded border my-2">
              <QRCodeSVG value={booking.reference} size={260} />
            </div>
            <div className="ref fs-2">{booking.reference}</div>
            <div className="fs-5">{booking.items.map((i) => `${i.quantity} × ${i.ticket_name}`).join(', ')}</div>
            <div className="fs-4 fw-bold">{formatINR(booking.total_amount)}</div>
            <div className="small text-muted">{t('partners.kiosk.showAtGate')}</div>
          </div>
        </div>
        <div className="d-flex justify-content-center flex-wrap gap-3 mt-4 no-print">
          <button type="button" className="btn btn-accent btn-lg px-5 py-3 fs-4" onClick={() => window.print()}>
            <i className="bi bi-printer me-2" aria-hidden="true" />{t('partners.kiosk.print')}
          </button>
          <button type="button" className="btn btn-outline-primary btn-lg px-5 py-3 fs-4" onClick={this.reset}>{t('partners.kiosk.done')}</button>
        </div>
        <p className="text-muted mt-3 no-print">{t('partners.kiosk.resetIn', { n: idleLeft })}</p>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { user, loading } = this.props.auth;
    const { me, meError, museum, screen } = this.state;
    let body: React.ReactNode;
    if (loading) body = null;
    else if (!user) body = this.renderSignIn();
    else if (!this.isKiosk()) {
      body = (
        <div className="container py-5 text-center" style={{ maxWidth: 560 }}>
          <i className="bi bi-tablet display-3 text-muted" aria-hidden="true" />
          <p className="fs-5 mt-3">{t('partners.kiosk.notKiosk')}</p>
          <button type="button" className="btn btn-outline-primary btn-lg" onClick={this.signOut}>{t('partners.kiosk.signOut')}</button>
        </div>
      );
    } else if (meError) body = <div className="container py-5"><div className="alert alert-danger fs-5">{meError}</div></div>;
    else if (!me) body = null;
    else if (screen === 'settings') body = this.renderSettings();
    else if (!museum) body = this.renderPlacePicker();
    else if (screen === 'pay') body = this.renderPay();
    else if (screen === 'done') body = this.renderDone();
    else body = this.renderTickets();

    return (
      <div className="position-fixed top-0 start-0 w-100 h-100 overflow-auto bg-light" style={{ zIndex: 1035 }}>
        {this.renderHeader()}
        <main>{body}</main>
      </div>
    );
  }
}

export default withAuth(withI18n(KioskBase));
