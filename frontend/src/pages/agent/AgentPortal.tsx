import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import type { AgentApplyInput, AgentBooking, AgentBookingInput, AgentMe, AgentStatement } from '../../api/partners';
import { Availability, GROUP_TYPES, GroupType, Museum, MuseumSummary, Paginated } from '../../api/types';
import { Empty, Loader, Pagination, StatusBadge } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatDateTime, formatINR, formatTime, isoDate } from '../../utils/format';

/** Tour-operator portal: apply, dashboard, book on account, bookings and monthly statement. */

type Tab = 'dashboard' | 'book' | 'bookings' | 'statement';
const TABS: { id: Tab; icon: string }[] = [
  { id: 'dashboard', icon: 'bi-bar-chart' },
  { id: 'book', icon: 'bi-calendar-event' },
  { id: 'bookings', icon: 'bi-receipt' },
  { id: 'statement', icon: 'bi-wallet2' },
];

const thisMonth = (): string => isoDate(0).slice(0, 7);

interface Props extends WithAuthProps, WithI18nProps {}

interface State {
  me: AgentMe | null;
  loadError: string;
  tab: Tab;
}

class AgentPortalBase extends React.Component<Props, State> {
  public state: State = { me: null, loadError: '', tab: 'dashboard' };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.loadMe();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private loadMe = (): void => {
    api
      .get<AgentMe>('/agents/me/')
      .then((r) => this.mounted && this.setState({ me: r.data, loadError: '' }))
      .catch((err) => this.mounted && this.setState({ loadError: errorMessage(err) }));
  };

  /** After approval the stored user still says "visitor" until refreshed. */
  private refreshUser = (): void => {
    api.get('/auth/me/').then((r) => this.props.auth.setUser(r.data)).catch(() => undefined);
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { me, loadError, tab } = this.state;
    if (loadError) return <div className="container py-5"><div className="alert alert-danger">{loadError}</div></div>;
    if (!me) return <Loader />;
    const profile = me.profile;

    return (
      <div className="container py-4 page">
        <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-4 no-print">
          <div>
            <h1 className="h2 mb-0">
              <i className="bi bi-briefcase me-2 text-primary" aria-hidden="true" />
              {t('partners.agent.title')}
            </h1>
            {profile?.is_approved && <div className="text-muted">{profile.company_name}</div>}
          </div>
        </div>

        {!profile || profile.status === 'rejected' ? (
          <ApplyForm rejectedNote={profile?.status === 'rejected' ? profile.admin_note || '-' : null} onApplied={this.loadMe} />
        ) : profile.status === 'pending' ? (
          <div className="card border-0 shadow-sm" style={{ maxWidth: 640 }}>
            <div className="card-body">
              <h2 className="h4"><i className="bi bi-hourglass-split me-2 text-warning" aria-hidden="true" />{t('partners.agent.pendingTitle')}</h2>
              <p className="mb-2">{t('partners.agent.pendingBody', { company: profile.company_name })}</p>
              <button type="button" className="btn btn-outline-primary btn-sm" onClick={() => { this.loadMe(); this.refreshUser(); }}>
                <i className="bi bi-arrow-repeat me-1" aria-hidden="true" />{t('partners.agent.checkAgain')}
              </button>
            </div>
          </div>
        ) : profile.status === 'suspended' ? (
          <div className="alert alert-warning" style={{ maxWidth: 640 }}>
            <i className="bi bi-exclamation-triangle me-2" aria-hidden="true" />
            {t('partners.agent.suspended')}
          </div>
        ) : (
          <>
            <ul className="nav nav-pills mb-4 flex-wrap gap-1 no-print" role="tablist">
              {TABS.map((x) => (
                <li className="nav-item" key={x.id} role="presentation">
                  <button type="button" role="tab" aria-selected={tab === x.id} className={`nav-link ${tab === x.id ? 'active' : ''}`} onClick={() => this.setState({ tab: x.id })}>
                    <i className={`bi ${x.icon} me-1`} aria-hidden="true" />
                    {t(`partners.agent.tab.${x.id}`)}
                  </button>
                </li>
              ))}
            </ul>
            {tab === 'dashboard' && <AgentDashboardView me={me} onBook={() => this.setState({ tab: 'book' })} />}
            {tab === 'book' && <AgentBookForm me={me} onBooked={this.loadMe} onShowBookings={() => this.setState({ tab: 'bookings' })} />}
            {tab === 'bookings' && <AgentBookingsList onChanged={this.loadMe} />}
            {tab === 'statement' && <AgentStatementView />}
          </>
        )}
      </div>
    );
  }
}

export default withAuth(withI18n(AgentPortalBase));

// ------------------------------------------------------------------------------------------- apply

interface ApplyProps extends WithI18nProps {
  rejectedNote: string | null;
  onApplied: () => void;
}

interface ApplyState {
  form: AgentApplyInput;
  error: string;
  busy: boolean;
}

class ApplyFormBase extends React.Component<ApplyProps, ApplyState> {
  public state: ApplyState = {
    form: { company_name: '', gstin: '', contact_phone: '', city: '', message: '' },
    error: '',
    busy: false,
  };

  private set = (key: keyof AgentApplyInput, value: string): void => {
    this.setState((s) => ({ form: { ...s.form, [key]: value } }));
  };

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    this.setState({ busy: true, error: '' });
    try {
      await api.post('/agents/apply/', this.state.form);
      this.props.onApplied();
    } catch (err) {
      this.setState({ error: errorMessage(err), busy: false });
    }
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { form, error, busy } = this.state;
    return (
      <div className="row g-4">
        <div className="col-lg-5">
          <h2 className="h4">{t('partners.apply.heading')}</h2>
          <p className="text-muted">{t('partners.apply.intro')}</p>
          <ul className="list-unstyled">
            {['benefit1', 'benefit2', 'benefit3', 'benefit4'].map((k) => (
              <li key={k} className="mb-2"><i className="bi bi-check2-circle text-success me-2" aria-hidden="true" />{t(`partners.apply.${k}`)}</li>
            ))}
          </ul>
        </div>
        <div className="col-lg-7">
          <form className="card border-0 shadow-sm" onSubmit={this.submit}>
            <div className="card-body">
              {this.props.rejectedNote !== null && (
                <div className="alert alert-warning">{t('partners.apply.rejected', { note: this.props.rejectedNote })}</div>
              )}
              {error && <div className="alert alert-danger" role="alert">{error}</div>}
              <div className="mb-3">
                <label htmlFor="ap-company" className="form-label">{t('partners.apply.company')}</label>
                <input id="ap-company" className="form-control" required maxLength={150} value={form.company_name} onChange={(e) => this.set('company_name', e.target.value)} />
              </div>
              <div className="row g-3 mb-3">
                <div className="col-md-6">
                  <label htmlFor="ap-phone" className="form-label">{t('partners.apply.phone')}</label>
                  <input id="ap-phone" className="form-control" required inputMode="tel" value={form.contact_phone} onChange={(e) => this.set('contact_phone', e.target.value)} />
                </div>
                <div className="col-md-6">
                  <label htmlFor="ap-city" className="form-label">{t('partners.apply.city')}</label>
                  <input id="ap-city" className="form-control" maxLength={80} value={form.city} onChange={(e) => this.set('city', e.target.value)} />
                </div>
              </div>
              <div className="mb-3">
                <label htmlFor="ap-gstin" className="form-label">{t('partners.apply.gstin')}</label>
                <input id="ap-gstin" className="form-control text-uppercase" maxLength={15} value={form.gstin} onChange={(e) => this.set('gstin', e.target.value)} />
                <div className="form-text">{t('partners.apply.gstinHint')}</div>
              </div>
              <div className="mb-3">
                <label htmlFor="ap-msg" className="form-label">{t('partners.apply.message')}</label>
                <textarea id="ap-msg" className="form-control" rows={3} value={form.message} onChange={(e) => this.set('message', e.target.value)} />
              </div>
              <button className="btn btn-accent" disabled={busy}>{busy ? t('partners.common.sending') : t('partners.apply.submit')}</button>
            </div>
          </form>
        </div>
      </div>
    );
  }
}

const ApplyForm = withI18n(ApplyFormBase);

// ------------------------------------------------------------------------------------------- dashboard

interface DashProps extends WithI18nProps {
  me: AgentMe;
  onBook: () => void;
}

class AgentDashboardViewBase extends React.Component<DashProps> {
  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { profile, dashboard } = this.props.me;
    if (!profile || !dashboard) return null;
    const limit = Number(dashboard.credit_limit);
    const used = Number(dashboard.credit_used);
    const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    const stats = [
      { label: t('partners.dash.monthBookings'), value: String(dashboard.this_month.bookings) },
      { label: t('partners.dash.monthVisitors'), value: String(dashboard.this_month.visitors) },
      { label: t('partners.dash.monthGross'), value: formatINR(dashboard.this_month.gross) },
      { label: t('partners.dash.monthCommission'), value: formatINR(dashboard.this_month.commission) },
    ];
    return (
      <div className="row g-4">
        <div className="col-lg-5">
          <div className="card border-0 shadow-sm h-100">
            <div className="card-body">
              <h2 className="h5">{t('partners.dash.credit')}</h2>
              <div className="d-flex justify-content-between small text-muted mb-1">
                <span>{t('partners.dash.used')}: {formatINR(used)}</span>
                <span>{t('partners.dash.limit')}: {formatINR(limit)}</span>
              </div>
              <div className="progress mb-3" style={{ height: 12 }} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t('partners.dash.credit')}>
                <div className={`progress-bar ${pct > 85 ? 'bg-danger' : 'bg-primary'}`} style={{ width: `${pct}%` }} />
              </div>
              <div className="stat-card">
                <div className="text-muted small">{t('partners.dash.available')}</div>
                <div className="stat-value">{formatINR(dashboard.credit_available)}</div>
              </div>
              <div className="small text-muted mt-2">
                {t('partners.dash.commissionRate', { pct: Number(profile.commission_percent) })} · {t('partners.dash.upcoming', { n: dashboard.upcoming_visits })}
              </div>
              <button type="button" className="btn btn-accent mt-3" onClick={this.props.onBook}>
                <i className="bi bi-calendar-event me-1" aria-hidden="true" />{t('partners.dash.bookNow')}
              </button>
            </div>
          </div>
        </div>
        <div className="col-lg-7">
          <div className="row g-3">
            {stats.map((s) => (
              <div className="col-6" key={s.label}>
                <div className="card border-0 shadow-sm stat-card h-100">
                  <div className="card-body">
                    <div className="text-muted small">{s.label}</div>
                    <div className="stat-value">{s.value}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="small text-muted mt-3 mb-0">{t('partners.dash.note')}</p>
        </div>
      </div>
    );
  }
}

const AgentDashboardView = withI18n(AgentDashboardViewBase);

// ------------------------------------------------------------------------------------------- booking form

interface BookProps extends WithI18nProps {
  me: AgentMe;
  onBooked: () => void;
  onShowBookings: () => void;
}

interface BookState {
  search: string;
  options: MuseumSummary[];
  museum: Museum | null;
  date: string;
  availability: Availability | null;
  slotId: number | null;
  qty: Record<number, number>;
  isGroup: boolean;
  groupType: GroupType;
  organisation: string;
  escorts: number;
  visitorName: string;
  visitorPhone: string;
  error: string;
  busy: boolean;
  done: AgentBooking | null;
}

class AgentBookFormBase extends React.Component<BookProps, BookState> {
  public state: BookState = {
    search: '', options: [], museum: null, date: isoDate(1), availability: null, slotId: null, qty: {},
    isGroup: false, groupType: 'tour_operator', organisation: this.props.me.profile?.company_name ?? '', escorts: 0,
    visitorName: '', visitorPhone: '', error: '', busy: false, done: null,
  };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  public componentDidUpdate(_p: BookProps, prev: BookState): void {
    if (prev.search !== this.state.search) this.scheduleSearch();
    if (prev.museum !== this.state.museum || prev.date !== this.state.date) this.loadAvailability();
  }

  private scheduleSearch(): void {
    clearTimeout(this.timer);
    const q = this.state.search.trim();
    if (!q) {
      this.setState({ options: [] });
      return;
    }
    this.timer = setTimeout(() => {
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search: q } })
        .then((r) => this.mounted && this.setState({ options: r.data.results }))
        .catch(() => undefined);
    }, 250);
  }

  private choose = (m: MuseumSummary): void => {
    this.setState({ search: '', options: [], museum: null, availability: null, slotId: null, qty: {} });
    api.get<Museum>(`/museums/${m.slug}/`).then((r) => this.mounted && this.setState({ museum: r.data }));
  };

  private loadAvailability(): void {
    const { museum, date } = this.state;
    if (!museum || !date) return;
    this.setState({ availability: null });
    api
      .get<Availability>(`/museums/${museum.slug}/availability/`, { params: { date } })
      .then((r) => {
        if (!this.mounted || this.state.date !== date) return;
        this.setState((s) => ({
          availability: r.data,
          slotId: r.data.slots.some((x) => x.id === s.slotId && x.bookable) ? s.slotId : null,
        }));
      })
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  }

  private step = (id: number, delta: number): void => {
    this.setState((s) => ({ qty: { ...s.qty, [id]: Math.max(0, (s.qty[id] ?? 0) + delta) } }));
  };

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { museum, slotId, date, qty, isGroup, groupType, organisation, escorts, visitorName, visitorPhone } = this.state;
    if (!museum || !slotId) return;
    const payload: AgentBookingInput = {
      museum: museum.slug,
      slot: slotId,
      visit_date: date,
      items: Object.entries(qty).filter(([, q]) => q > 0).map(([id, q]) => ({ ticket_type: Number(id), quantity: q })),
      visitor_name: visitorName.trim() || organisation.trim() || (this.props.me.profile?.company_name ?? ''),
      visitor_phone: visitorPhone.trim() || undefined,
    };
    if (isGroup) Object.assign(payload, { group_type: groupType, organisation_name: organisation, escort_count: escorts });
    this.setState({ busy: true, error: '' });
    try {
      const { data } = await api.post<AgentBooking>('/agents/bookings/', payload);
      this.setState({ done: data, qty: {}, visitorName: '', visitorPhone: '', busy: false });
      this.props.onBooked();
      this.loadAvailability();
    } catch (err) {
      this.setState({ error: errorMessage(err), busy: false });
    }
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const s = this.state;
    const profile = this.props.me.profile!;
    const tickets = (s.museum?.ticket_types ?? []).filter((x) => x.is_active);
    const count = Object.values(s.qty).reduce((a, b) => a + b, 0);
    const estimate = tickets.reduce((sum, x) => sum + Number(x.price) * (s.qty[x.id!] ?? 0), 0);
    const policy = s.museum?.group_policy;
    const max = s.isGroup ? policy?.max_size ?? 60 : 20;
    const slot = s.availability?.slots.find((x) => x.id === s.slotId);
    const educational = GROUP_TYPES.find((g) => g.value === s.groupType)?.educational ?? false;

    if (s.done) {
      return (
        <div className="card border-0 shadow-sm" style={{ maxWidth: 640 }}>
          <div className="card-body">
            <div className="alert alert-success">
              <i className="bi bi-check-circle-fill me-2" aria-hidden="true" />
              {t('partners.book.done', { ref: s.done.reference })}
            </div>
            <dl className="row mb-3">
              <dt className="col-5">{t('partners.common.place')}</dt><dd className="col-7">{s.done.museum_name}</dd>
              <dt className="col-5">{t('partners.common.visit')}</dt><dd className="col-7">{formatDate(s.done.visit_date)} · {formatTime(s.done.slot_start)}</dd>
              <dt className="col-5">{t('partners.common.visitors')}</dt><dd className="col-7">{s.done.total_visitors}</dd>
              <dt className="col-5">{t('partners.common.amount')}</dt><dd className="col-7">{formatINR(s.done.total_amount)}</dd>
              <dt className="col-5">{t('partners.common.commission')}</dt><dd className="col-7">{formatINR(s.done.commission_amount)}</dd>
            </dl>
            <div className="d-flex flex-wrap gap-2">
              <Link className="btn btn-accent" to={`/tickets/${s.done.reference}`}><i className="bi bi-printer me-1" aria-hidden="true" />{t('partners.book.openTicket')}</Link>
              <button type="button" className="btn btn-outline-primary" onClick={() => this.setState({ done: null })}>{t('partners.book.another')}</button>
              <button type="button" className="btn btn-link" onClick={this.props.onShowBookings}>{t('partners.book.allBookings')}</button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <form className="row g-4" onSubmit={this.submit}>
        <div className="col-lg-8">
          <div className="card border-0 shadow-sm">
            <div className="card-body">
              {s.error && <div className="alert alert-danger" role="alert">{s.error}</div>}
              <div className="mb-3 position-relative">
                <label htmlFor="ag-place" className="form-label fw-semibold">{t('partners.book.place')}</label>
                <input id="ag-place" className="form-control" autoComplete="off" placeholder={s.museum ? s.museum.name : t('partners.book.placeSearch')} value={s.search} onChange={(e) => this.setState({ search: e.target.value })} />
                {s.museum && !s.search && <div className="form-text">{t('partners.book.selected')}: <strong className="text-body">{s.museum.name}</strong>, {s.museum.city_name}</div>}
                {s.options.length > 0 && (
                  <div className="list-group shadow position-absolute w-100" style={{ top: '100%', left: 0, zIndex: 10, maxHeight: 280, overflowY: 'auto' }}>
                    {s.options.map((m) => (
                      <button type="button" key={m.id} className="list-group-item list-group-item-action" onClick={() => this.choose(m)}>
                        {m.name} <span className="small text-muted">· {m.city_name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {s.museum && (
                <>
                  <div className="row g-3 mb-3">
                    <div className="col-sm-6">
                      <label htmlFor="ag-date" className="form-label fw-semibold">{t('partners.book.date')}</label>
                      <input id="ag-date" type="date" className="form-control" min={isoDate(0)} max={isoDate(90)} value={s.date} required onChange={(e) => this.setState({ date: e.target.value })} />
                    </div>
                    <div className="col-sm-6 d-flex align-items-end">
                      <div className="form-check form-switch">
                        <input id="ag-group" className="form-check-input" type="checkbox" disabled={!(s.museum.groups_open ?? s.museum.allow_groups)} checked={s.isGroup} onChange={(e) => this.setState({ isGroup: e.target.checked })} />
                        <label htmlFor="ag-group" className="form-check-label">
                          {t('partners.book.group', { min: policy?.min_size ?? 21, max: policy?.max_size ?? 60 })}
                        </label>
                      </div>
                    </div>
                  </div>

                  <div className="mb-3">
                    <span className="form-label fw-semibold d-block">{t('partners.book.slot')}</span>
                    {!s.availability ? <Loader /> : s.availability.closed ? (
                      <div className="alert alert-warning mb-0">{t('partners.book.closed')}</div>
                    ) : (
                      <div className="row g-2">
                        {s.availability.slots.map((x) => {
                          const left = s.isGroup ? Math.min(x.available, x.group_available) : x.available;
                          return (
                            <div className="col-6 col-md-4" key={x.id}>
                              <button type="button" className={`btn slot-btn w-100 ${s.slotId === x.id ? 'btn-primary' : 'btn-outline-primary'}`} disabled={!x.bookable || left <= 0} aria-pressed={s.slotId === x.id} onClick={() => this.setState({ slotId: x.id })}>
                                <strong>{formatTime(x.start_time)} – {formatTime(x.end_time)}</strong>
                                <small>{left <= 0 ? t('partners.book.full') : !x.bookable ? t('partners.book.unavailable') : t('partners.book.left', { n: left })}</small>
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <ul className="list-group list-group-flush mb-3">
                    {tickets.map((x) => (
                      <li key={x.id} className="list-group-item d-flex justify-content-between align-items-center gap-3 px-0">
                        <div>
                          <div className="fw-semibold">{x.name}</div>
                          <div className="text-muted small">{formatINR(x.price)}</div>
                        </div>
                        <div className="input-group input-group-sm" style={{ width: 130 }}>
                          <button type="button" className="btn btn-outline-primary" aria-label={t('partners.common.fewer', { name: x.name })} disabled={!s.qty[x.id!]} onClick={() => this.step(x.id!, -1)}>
                            <i className="bi bi-dash-lg" aria-hidden="true" />
                          </button>
                          <span className="form-control text-center fw-semibold" aria-live="polite">{s.qty[x.id!] ?? 0}</span>
                          <button type="button" className="btn btn-outline-primary" aria-label={t('partners.common.more', { name: x.name })} disabled={count >= max} onClick={() => this.step(x.id!, 1)}>
                            <i className="bi bi-plus-lg" aria-hidden="true" />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>

                  {s.isGroup && (
                    <div className="row g-3 mb-3">
                      <div className="col-md-4">
                        <label htmlFor="ag-gtype" className="form-label">{t('partners.book.groupType')}</label>
                        <select id="ag-gtype" className="form-select" value={s.groupType} onChange={(e) => this.setState({ groupType: e.target.value as GroupType, escorts: 0 })}>
                          {GROUP_TYPES.map((g) => <option key={g.value} value={g.value}>{t(`common.groupType.${g.value}`)}</option>)}
                        </select>
                      </div>
                      <div className="col-md-5">
                        <label htmlFor="ag-org" className="form-label">{t('partners.book.organisation')}</label>
                        <input id="ag-org" className="form-control" required maxLength={150} value={s.organisation} onChange={(e) => this.setState({ organisation: e.target.value })} />
                      </div>
                      {educational && (
                        <div className="col-md-3">
                          <label htmlFor="ag-esc" className="form-label">{t('partners.book.escorts')}</label>
                          <input id="ag-esc" type="number" min={0} className="form-control" value={s.escorts} onChange={(e) => this.setState({ escorts: Math.max(0, Number(e.target.value) || 0) })} />
                        </div>
                      )}
                    </div>
                  )}

                  <div className="row g-3">
                    <div className="col-md-7">
                      <label htmlFor="ag-name" className="form-label">{t('partners.book.visitorName')}</label>
                      <input id="ag-name" className="form-control" maxLength={120} value={s.visitorName} placeholder={s.isGroup ? s.organisation : t('partners.book.visitorNameHint')} required={!s.isGroup} onChange={(e) => this.setState({ visitorName: e.target.value })} />
                    </div>
                    <div className="col-md-5">
                      <label htmlFor="ag-phone" className="form-label">{t('partners.book.visitorPhone')}</label>
                      <input id="ag-phone" className="form-control" inputMode="tel" placeholder={profile.contact_phone} value={s.visitorPhone} onChange={(e) => this.setState({ visitorPhone: e.target.value })} />
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="col-lg-4">
          <div className="card border-0 shadow-sm booking-panel">
            <div className="card-body">
              <h2 className="h5">{t('partners.book.summary')}</h2>
              <div className="d-flex justify-content-between"><span>{t('partners.common.visitors')}</span><strong>{count + (s.isGroup ? s.escorts : 0)}</strong></div>
              <div className="d-flex justify-content-between"><span>{t('partners.book.estimate')}</span><strong>{formatINR(estimate)}</strong></div>
              <div className="d-flex justify-content-between text-muted small"><span>{t('partners.book.creditAvailable')}</span><span>{formatINR(profile.credit_available)}</span></div>
              <p className="small text-muted mt-2">{t('partners.book.estimateNote')}</p>
              <button className="btn btn-accent w-100" disabled={s.busy || !s.museum || !slot || count === 0}>
                {s.busy ? t('partners.common.sending') : t('partners.book.submit')}
              </button>
            </div>
          </div>
        </div>
      </form>
    );
  }
}

const AgentBookForm = withI18n(AgentBookFormBase);

// ------------------------------------------------------------------------------------------- bookings list

interface ListProps extends WithI18nProps {
  onChanged: () => void;
}

interface ListState {
  page: number;
  data: Paginated<AgentBooking> | null;
  search: string;
  upcoming: boolean;
  error: string;
  info: string;
}

class AgentBookingsListBase extends React.Component<ListProps, ListState> {
  public state: ListState = { page: 1, data: null, search: '', upcoming: false, error: '', info: '' };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  public componentDidUpdate(_p: ListProps, prev: ListState): void {
    if (prev.page !== this.state.page || prev.upcoming !== this.state.upcoming) this.load();
    if (prev.search !== this.state.search) {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => (this.state.page === 1 ? this.load() : this.setState({ page: 1 })), 300);
    }
  }

  private load = (): void => {
    const { page, search, upcoming } = this.state;
    api
      .get<Paginated<AgentBooking>>('/agents/bookings/', { params: { page, search: search || undefined, upcoming: upcoming ? 1 : undefined } })
      .then((r) => this.mounted && this.setState({ data: r.data }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  };

  private cancel = async (b: AgentBooking): Promise<void> => {
    const { t } = this.props.i18n;
    if (!window.confirm(t('partners.list.confirmCancel', { ref: b.reference }))) return;
    try {
      await api.post(`/agents/bookings/${b.reference}/cancel/`);
      this.setState({ info: t('partners.list.cancelled', { ref: b.reference }), error: '' });
      this.load();
      this.props.onChanged();
    } catch (err) {
      this.setState({ error: errorMessage(err), info: '' });
    }
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { data, page, search, upcoming, error, info } = this.state;
    return (
      <div>
        <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
          <input className="form-control" style={{ maxWidth: 320 }} placeholder={t('partners.list.search')} aria-label={t('partners.list.search')} value={search} onChange={(e) => this.setState({ search: e.target.value })} />
          <div className="form-check ms-2">
            <input id="ag-up" type="checkbox" className="form-check-input" checked={upcoming} onChange={(e) => this.setState({ upcoming: e.target.checked, page: 1 })} />
            <label htmlFor="ag-up" className="form-check-label">{t('partners.list.upcoming')}</label>
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        {info && <div className="alert alert-success">{info}</div>}
        {!data ? <Loader /> : data.results.length === 0 ? <Empty title={t('partners.list.empty')} /> : (
          <div className="table-responsive card border-0 shadow-sm">
            <table className="table table-hover align-middle mb-0">
              <thead className="table-light">
                <tr>
                  <th>{t('partners.common.reference')}</th>
                  <th>{t('partners.common.place')}</th>
                  <th>{t('partners.common.visit')}</th>
                  <th>{t('partners.list.party')}</th>
                  <th className="text-end">{t('partners.common.amount')}</th>
                  <th className="text-end">{t('partners.common.commission')}</th>
                  <th>{t('partners.common.status')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.results.map((b) => (
                  <tr key={b.reference}>
                    <td><Link className="ref" to={`/tickets/${b.reference}`}>{b.reference}</Link></td>
                    <td>{b.museum_name}<div className="small text-muted">{b.city_name}</div></td>
                    <td>{formatDate(b.visit_date)}<div className="small text-muted">{formatTime(b.slot_start)}</div></td>
                    <td>{b.organisation_name || b.visitor_name}<div className="small text-muted">{t('partners.list.people', { n: b.total_visitors })}</div></td>
                    <td className="text-end">{formatINR(b.total_amount)}</td>
                    <td className="text-end">{formatINR(b.commission_amount)}</td>
                    <td><StatusBadge status={b.status} /></td>
                    <td className="text-end text-nowrap">
                      <Link className="btn btn-sm btn-outline-primary me-1" to={`/tickets/${b.reference}`} aria-label={t('partners.list.ticket')}>
                        <i className="bi bi-printer" aria-hidden="true" />
                      </Link>
                      {b.agent_can_cancel && (
                        <button type="button" className="btn btn-sm btn-outline-danger" onClick={() => this.cancel(b)}>{t('partners.list.cancel')}</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />}
        <p className="small text-muted mt-3">{t('partners.list.cancelRule')}</p>
      </div>
    );
  }
}

const AgentBookingsList = withI18n(AgentBookingsListBase);

// ------------------------------------------------------------------------------------------- statement

interface StatementState {
  month: string;
  data: AgentStatement | null;
  error: string;
}

class AgentStatementViewBase extends React.Component<WithI18nProps, StatementState> {
  public state: StatementState = { month: thisMonth(), data: null, error: '' };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public componentDidUpdate(_p: WithI18nProps, prev: StatementState): void {
    if (prev.month !== this.state.month) this.load();
  }

  private load(): void {
    const { month } = this.state;
    if (!/^\d{4}-\d{2}$/.test(month)) return;
    this.setState({ data: null, error: '' });
    api
      .get<AgentStatement>('/agents/statement/', { params: { month } })
      .then((r) => this.mounted && this.state.month === month && this.setState({ data: r.data }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { month, data, error } = this.state;
    return (
      <div>
        <div className="d-flex flex-wrap gap-2 align-items-end mb-3 no-print">
          <div>
            <label htmlFor="ag-month" className="form-label">{t('partners.statement.month')}</label>
            <input id="ag-month" type="month" className="form-control" value={month} max={thisMonth()} onChange={(e) => this.setState({ month: e.target.value })} />
          </div>
          <button type="button" className="btn btn-outline-primary" disabled={!data} onClick={() => window.print()}>
            <i className="bi bi-printer me-1" aria-hidden="true" />{t('partners.statement.print')}
          </button>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        {!data ? (!error && <Loader />) : (
          <div className="card border-0 shadow-sm">
            <div className="card-body">
              <div className="d-flex flex-wrap justify-content-between gap-2 mb-3">
                <div>
                  <div className="text-muted small">ANCIENT ANTIQUITY · {t('partners.statement.title').toUpperCase()}</div>
                  <h2 className="h4 mb-0">{data.company_name}</h2>
                  {data.gstin && <div className="small">GSTIN {data.gstin}</div>}
                </div>
                <div className="text-end">
                  <div className="fw-semibold">{formatDate(data.from, { month: 'long', year: 'numeric' })}</div>
                  <div className="small text-muted">{formatDate(data.from)} – {formatDate(data.to)}</div>
                </div>
              </div>
              <div className="row g-3 mb-3">
                {[
                  [t('partners.statement.gross'), formatINR(data.gross)],
                  [t('partners.statement.commission', { pct: Number(data.commission_percent) }), `− ${formatINR(data.commission)}`],
                  [t('partners.statement.net'), formatINR(data.net_payable)],
                  [t('partners.statement.received'), formatINR(data.payments_received)],
                  [t('partners.statement.outstanding'), formatINR(data.outstanding_balance)],
                ].map(([label, value]) => (
                  <div className="col-6 col-md" key={label}>
                    <div className="fact"><span className="label">{label}</span><strong>{value}</strong></div>
                  </div>
                ))}
              </div>
              {data.bookings.length === 0 ? <p className="text-muted">{t('partners.statement.none')}</p> : (
                <div className="table-responsive">
                  <table className="table table-sm align-middle">
                    <thead>
                      <tr>
                        <th>{t('partners.statement.booked')}</th>
                        <th>{t('partners.common.reference')}</th>
                        <th>{t('partners.common.place')}</th>
                        <th>{t('partners.common.visit')}</th>
                        <th className="text-end">{t('partners.common.visitors')}</th>
                        <th className="text-end">{t('partners.common.amount')}</th>
                        <th className="text-end">{t('partners.common.commission')}</th>
                        <th>{t('partners.common.status')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.bookings.map((b) => (
                        <tr key={b.reference} className={b.status === 'cancelled' ? 'text-muted' : ''}>
                          <td>{formatDate(b.created_at)}</td>
                          <td className="ref">{b.reference}</td>
                          <td>{b.museum_name}</td>
                          <td>{formatDate(b.visit_date)} {formatTime(b.slot_start)}</td>
                          <td className="text-end">{b.total_visitors}</td>
                          <td className="text-end">{b.status === 'cancelled' ? <s>{formatINR(b.total_amount)}</s> : formatINR(b.total_amount)}</td>
                          <td className="text-end">{b.status === 'cancelled' ? '–' : formatINR(b.commission_amount)}</td>
                          <td>{t(`common.status.${b.status}`)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data.payments.length > 0 && (
                <>
                  <h3 className="h6 mt-3">{t('partners.statement.payments')}</h3>
                  <table className="table table-sm">
                    <tbody>
                      {data.payments.map((p) => (
                        <tr key={p.id}>
                          <td>{formatDate(p.received_on)}</td>
                          <td>{p.reference}</td>
                          <td className="text-end">{formatINR(p.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
              <p className="small text-muted mb-0">{t('partners.statement.footer', { when: formatDateTime(new Date().toISOString()) })}</p>
            </div>
          </div>
        )}
      </div>
    );
  }
}

const AgentStatementView = withI18n(AgentStatementViewBase);
