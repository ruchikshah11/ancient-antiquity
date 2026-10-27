import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { KIND_ICONS } from '../../api/events';
import type { EventDetail as EventDetailData, EventSessionInfo } from '../../api/events';
import type { Booking } from '../../api/types';
import AuthModal from '../../components/AuthModal';
import { Empty, Loader } from '../../components/Common';
import WaitlistButton from '../../components/WaitlistButton';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatINR, formatPrice, formatTime, museumGradient, sizedImage } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import FxHint from '../../components/FxHint';

/*
 * /events/:slug — one event or show: description, pick a date and session, choose tickets, then book.
 * Signed-out visitors get the AuthModal first. The booking is paid on the normal /checkout/<ref> page.
 * ?date=YYYY-MM-DD preselects a date (used by waitlist notifications).
 */

const MAX_TICKETS = 20;

interface Visitor {
  name: string;
  email: string;
  phone: string;
}

type EventDetailProps = WithRouterProps & WithAuthProps & WithI18nProps;

interface EventDetailState {
  event: EventDetailData | null | undefined;
  date: string;
  sessionId: number | null;
  qty: Record<number, number>;
  visitor: Visitor;
  authOpen: boolean;
  submitting: boolean;
  error: string;
}

class EventDetail extends React.Component<EventDetailProps, EventDetailState> {
  public state: EventDetailState = {
    event: undefined,
    date: '',
    sessionId: null,
    qty: {},
    visitor: { name: '', email: '', phone: '' },
    authOpen: false,
    submitting: false,
    error: '',
  };

  private mounted = false;
  private request = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
    this.prefillVisitor();
  }

  public componentDidUpdate(prevProps: EventDetailProps): void {
    if (prevProps.router.params.slug !== this.props.router.params.slug) this.load();
    if (prevProps.auth.user !== this.props.auth.user) this.prefillVisitor();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private prefillVisitor(): void {
    const { user } = this.props.auth;
    if (!user) return;
    this.setState((s) => ({
      visitor: {
        name: s.visitor.name || `${user.first_name} ${user.last_name}`.trim(),
        email: s.visitor.email || user.email,
        phone: s.visitor.phone || user.phone || '',
      },
    }));
  }

  /** Availability changes all the time, so this is never served from the offline cache. */
  private load(keepSelection = false): void {
    const id = ++this.request;
    const slug = this.props.router.params.slug ?? '';
    api
      .get<EventDetailData>(`/events/${slug}/`)
      .then(({ data }) => {
        if (!this.mounted || id !== this.request) return;
        const dates = this.dates(data);
        const wanted = this.props.router.searchParams.get('date') ?? '';
        this.setState((s) => ({
          event: data,
          date: keepSelection && dates.includes(s.date) ? s.date : dates.includes(wanted) ? wanted : dates[0] ?? '',
          sessionId: keepSelection ? s.sessionId : null,
        }));
      })
      .catch(() => this.mounted && id === this.request && this.setState({ event: null }));
  }

  private dates(event: EventDetailData | null | undefined = this.state.event): string[] {
    return Array.from(new Set((event?.sessions ?? []).map((s) => s.date)));
  }

  private selected(): EventSessionInfo | undefined {
    return this.state.event?.sessions.find((s) => s.id === this.state.sessionId);
  }

  private count(): number {
    return Object.values(this.state.qty).reduce((a, b) => a + b, 0);
  }

  private cap(): number {
    return Math.min(MAX_TICKETS, this.selected()?.available ?? MAX_TICKETS);
  }

  private change(id: number, delta: number): void {
    this.setState((s) => {
      const current = s.qty[id] ?? 0;
      const others = Object.values(s.qty).reduce((a, b) => a + b, 0) - current;
      const next = Math.max(0, Math.min(current + delta, this.cap() - others));
      return { qty: { ...s.qty, [id]: next }, error: '' };
    });
  }

  private setVisitor = (k: keyof Visitor) => (e: React.ChangeEvent<HTMLInputElement>): void =>
    this.setState({ visitor: { ...this.state.visitor, [k]: e.target.value } });

  private submit = (e: React.FormEvent): void => {
    e.preventDefault();
    if (!this.props.auth.user) this.setState({ authOpen: true });
    else this.book();
  };

  private book = async (): Promise<void> => {
    const { event, sessionId, qty, visitor } = this.state;
    if (!event || !sessionId) return;
    this.setState({ authOpen: false, submitting: true, error: '' });
    try {
      const { data } = await api.post<Booking>('/events/bookings/', {
        session: sessionId,
        items: event.prices.map((p) => ({ price: p.id, quantity: qty[p.id] ?? 0 })).filter((i) => i.quantity > 0),
        visitor_name: visitor.name,
        visitor_email: visitor.email,
        visitor_phone: visitor.phone,
      });
      this.props.router.navigate(data.status === 'confirmed' ? `/tickets/${data.reference}` : `/checkout/${data.reference}`);
    } catch (err) {
      if (!this.mounted) return;
      this.setState({ error: errorMessage(err) });
      this.load(true);
    } finally {
      if (this.mounted) this.setState({ submitting: false });
    }
  };

  private renderSessions(event: EventDetailData): React.ReactNode {
    const { t } = this.props.i18n;
    const { date, sessionId } = this.state;
    const dates = this.dates();
    const sessions = event.sessions.filter((s) => s.date === date);
    return (
      <>
        <div className="mb-3">
          <label htmlFor="ev-date" className="form-label">{t('events.date')}</label>
          <select id="ev-date" className="form-select" value={date} onChange={(e) => this.setState({ date: e.target.value, sessionId: null })}>
            {dates.map((d) => (
              <option key={d} value={d}>{formatDate(d, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}</option>
            ))}
          </select>
        </div>
        <div className="mb-3">
          <span className="form-label d-block">{t('events.session')}</span>
          <div className="row g-2">
            {sessions.map((s) => (
              <div key={s.id} className="col-6">
                <button
                  type="button"
                  className={`btn slot-btn w-100 ${sessionId === s.id ? 'btn-primary' : 'btn-outline-primary'}`}
                  aria-pressed={sessionId === s.id}
                  disabled={s.available === 0}
                  onClick={() => this.setState({ sessionId: s.id, qty: {} })}
                >
                  <strong>{formatTime(s.start_time)}</strong>
                  <small className={s.available > 0 && s.available <= 10 && sessionId !== s.id ? 'text-accent' : undefined}>
                    {s.closed_reason ? t('events.closed') : s.sold_out ? t('events.soldOut') : t('events.left', { n: s.available })}
                  </small>
                </button>
                {s.sold_out && (
                  <WaitlistButton
                    target={{ event_session: s.id }}
                    label={`${event.title}, ${formatDate(s.date, { day: 'numeric', month: 'short' })} ${formatTime(s.start_time)}`}
                    className="mt-1"
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      </>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { user } = this.props.auth;
    const { event, qty, visitor, authOpen, submitting, error, sessionId } = this.state;
    if (event === undefined) return <Loader />;
    if (event === null)
      return (
        <div className="container page py-4 py-lg-5">
          <Empty title={t('events.notFound')}>
            <Link to="/events" className="btn btn-outline-primary">{t('events.all')}</Link>
          </Empty>
        </div>
      );

    const image = event.image_url || event.museum_image;
    const count = this.count();
    const total = event.prices.reduce((sum, p) => sum + Number(p.price) * (qty[p.id] ?? 0), 0);
    const session = this.selected();

    return (
      <div className="container page py-4 py-lg-5">
        <div className="detail-hero mb-4" style={{ background: image ? `center / cover no-repeat url("${sizedImage(image, 1280)}")` : museumGradient(event.slug) }}>
          <div>
            <div className="d-flex flex-wrap gap-2 mb-2">
              <span className="badge bg-accent">
                <i className={`bi ${KIND_ICONS[event.kind]} me-1`} aria-hidden="true" />
                {t(`events.kind.${event.kind}`)}
              </span>
            </div>
            <h1 className="display-5 mb-1">{event.title}</h1>
            <div>
              <i className="bi bi-geo-alt-fill me-1" aria-hidden="true" />
              <Link to={`/museums/${event.museum_slug}`} className="text-reset">{event.museum_name}</Link>, {event.city_name}
            </div>
          </div>
        </div>

        <div className="row g-4">
          <div className="col-lg-8">
            <div className="row g-2 mb-4">
              <div className="col-sm-6 col-md-4">
                <div className="fact">
                  <span className="label"><i className="bi bi-stopwatch me-1" aria-hidden="true" />{t('events.duration')}</span>
                  <strong>{t('events.minutes', { n: event.duration_minutes })}</strong>
                </div>
              </div>
              {event.language && (
                <div className="col-sm-6 col-md-4">
                  <div className="fact">
                    <span className="label"><i className="bi bi-translate me-1" aria-hidden="true" />{t('events.language')}</span>
                    <strong>{event.language}</strong>
                  </div>
                </div>
              )}
              <div className="col-sm-6 col-md-4">
                <div className="fact">
                  <span className="label"><i className="bi bi-calendar-event me-1" aria-hidden="true" />{t('events.sessions')}</span>
                  <strong>{event.sessions.length}</strong>
                </div>
              </div>
            </div>
            <p style={{ whiteSpace: 'pre-line' }}>{event.description}</p>

            <h3 className="mt-4">{t('events.prices')}</h3>
            <div className="card border-0 shadow-sm mb-4">
              <ul className="list-group list-group-flush">
                {event.prices.map((p) => (
                  <li key={p.id} className="list-group-item d-flex justify-content-between">
                    <span>{p.name}</span>
                    <strong>{Number(p.price) === 0 ? t('common.free') : formatPrice(p.price)}</strong>
                  </li>
                ))}
              </ul>
            </div>
            <p className="text-muted small">
              <i className="bi bi-info-circle me-1" aria-hidden="true" />
              {t('events.ticketNote')}
            </p>
          </div>

          <div className="col-lg-4">
            <div className="booking-panel">
              <form className="card border-0 shadow" onSubmit={this.submit}>
                <div className="card-body p-4">
                  <h2 className="h4 mb-3">{t('events.book')}</h2>
                  {error && <div className="alert alert-danger" role="alert">{error}</div>}
                  {event.sessions.length === 0 ? (
                    <div className="alert alert-info mb-0">{t('events.noSessions')}</div>
                  ) : (
                    <>
                      {this.renderSessions(event)}
                      <div className="mb-3">
                        <span className="form-label d-block mb-1">{t('events.tickets')}</span>
                        {event.prices.map((p) => (
                          <div key={p.id} className="d-flex justify-content-between align-items-center py-2 border-bottom">
                            <div>
                              <div className="fw-semibold">{p.name}</div>
                              <div className="text-muted small">{Number(p.price) === 0 ? t('common.free') : formatPrice(p.price)}</div>
                            </div>
                            <div className="input-group input-group-sm flex-nowrap" style={{ width: 110 }}>
                              <button type="button" className="btn btn-outline-primary" aria-label={t('events.fewer', { name: p.name })} disabled={!qty[p.id]} onClick={() => this.change(p.id, -1)}>−</button>
                              <span className="form-control text-center bg-white" aria-live="polite">{qty[p.id] ?? 0}</span>
                              <button type="button" className="btn btn-outline-primary" aria-label={t('events.more', { name: p.name })} disabled={!sessionId || count >= this.cap()} onClick={() => this.change(p.id, 1)}>+</button>
                            </div>
                          </div>
                        ))}
                        {!sessionId && <div className="form-text">{t('events.pickSession')}</div>}
                      </div>
                      {count > 0 && (
                        <div className="mb-2">
                          <div className="mb-3">
                            <label htmlFor="ev-name" className="form-label">{t('events.visitor.name')}</label>
                            <input id="ev-name" className="form-control" value={visitor.name} onChange={this.setVisitor('name')} required />
                          </div>
                          <div className="mb-3">
                            <label htmlFor="ev-email" className="form-label">{t('events.visitor.email')}</label>
                            <input id="ev-email" type="email" className="form-control" value={visitor.email} onChange={this.setVisitor('email')} required />
                          </div>
                          <div className="mb-3">
                            <label htmlFor="ev-phone" className="form-label">{t('events.visitor.phone')}</label>
                            <input id="ev-phone" className="form-control" inputMode="tel" pattern="\+?[0-9]{10,13}" placeholder="9876543210" value={visitor.phone} onChange={this.setVisitor('phone')} required />
                          </div>
                        </div>
                      )}
                      <div className="d-flex justify-content-between fs-5 fw-bold my-3">
                        <span>{t('events.total', { n: count })}</span>
                        <span className="text-end">{formatINR(total)}<FxHint amount={total} className="d-block fs-6 fw-normal" /></span>
                      </div>
                      <button className="btn btn-accent btn-lg w-100" disabled={!sessionId || count === 0 || submitting}>
                        {submitting ? t('events.reserving') : total === 0 && count > 0 ? t('events.getFree') : t('events.continuePay')}
                      </button>
                      {!user && count > 0 && <p className="text-muted small text-center mt-2 mb-0">{t('events.loginHint')}</p>}
                      {session && (
                        <p className="text-muted small text-center mt-2 mb-0">
                          <i className="bi bi-calendar-event me-1" aria-hidden="true" />
                          {formatDate(session.date, { weekday: 'short', day: 'numeric', month: 'short' })}, {formatTime(session.start_time)} – {formatTime(session.end_time)}
                        </p>
                      )}
                    </>
                  )}
                </div>
              </form>
              <Link to="/events" className="btn btn-link btn-sm px-1 text-decoration-none mt-1">
                <i className="bi bi-arrow-left me-1" aria-hidden="true" />
                {t('events.all')}
              </Link>
            </div>
          </div>
        </div>

        <AuthModal
          open={authOpen}
          title={t('events.auth.title')}
          reason={t('events.auth.reason', { n: count })}
          prefill={visitor}
          onClose={() => this.setState({ authOpen: false })}
          onDone={this.book}
        />
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(EventDetail)));
