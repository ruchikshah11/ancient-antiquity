import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { formatKm, haversineKm, MAX_TRIP_DAYS, Trip, TripInput, TripStop, TripSummary, tripsApi } from '../../api/trips';
import type { MuseumSummary, Paginated } from '../../api/types';
import { Empty, Loader } from '../../components/Common';
import { withI18n, WithI18nProps } from '../../i18n';
import { djangoWeekday, formatDate, formatINR, formatTime, isoDate, museumGradient, sizedImage } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

type TripPlannerProps = WithRouterProps & WithI18nProps;

interface TripPlannerState {
  // list
  trips: TripSummary[] | null;
  form: TripInput;
  // detail
  trip: Trip | null;
  notFound: boolean;
  editing: boolean;
  extraDays: number;
  // add places
  query: string;
  results: MuseumSummary[] | null;
  addDay: number;
  // shared
  busy: boolean;
  error: string;
  // "Book all" summary
  showBookAll: boolean;
}

/**
 * Extra fields the trips API sends with each stop: the planned date (start date + day - 1), the slot nearest
 * the planned time (dated stops only) and the lowest ticket price on that date (weekend / season prices).
 */
type PlannedStop = TripStop & { visit_date?: string | null; slot_id?: number | null; price_on_date?: string | null };

/** Where a stop's "Book" link goes: the place page with the planned date (and slot) preselected. */
interface BookTarget {
  date: string | null;
  /** The planned date is before today: no booking link. */
  passed: boolean;
  url: string;
}

const EMPTY_FORM: TripInput = { title: '', start_date: null, end_date: null, notes: '' };

/** YYYY-MM-DD of day n (1-based) of a trip starting on `start`. */
function dayDate(start: string, n: number): string {
  const d = new Date(`${start}T00:00:00`);
  d.setDate(d.getDate() + n - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Trip list (/trips) and trip detail (/trips/:id). Login required: the lead wraps the routes in RequireAuth. */
class TripPlanner extends React.Component<TripPlannerProps, TripPlannerState> {
  public state: TripPlannerState = {
    trips: null,
    form: EMPTY_FORM,
    trip: null,
    notFound: false,
    editing: false,
    extraDays: 0,
    query: '',
    results: null,
    addDay: 1,
    busy: false,
    error: '',
    showBookAll: false,
  };

  private mounted = false;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  private searchRequest = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentDidUpdate(prev: TripPlannerProps): void {
    if (prev.router.params.id !== this.props.router.params.id) this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    if (this.searchTimer) clearTimeout(this.searchTimer);
  }

  private get tripId(): string | undefined {
    return this.props.router.params.id;
  }

  private load(): void {
    this.setState({ error: '', notFound: false, editing: false, extraDays: 0, query: '', results: null, addDay: 1, showBookAll: false });
    const id = this.tripId;
    if (!id) {
      this.setState({ trip: null, trips: null });
      tripsApi
        .list()
        .then((trips) => this.mounted && this.setState({ trips }))
        .catch((err) => this.mounted && this.setState({ trips: [], error: errorMessage(err) }));
      return;
    }
    this.setState({ trip: null });
    tripsApi
      .get(id)
      .then((trip) => this.mounted && this.setState({ trip }))
      .catch(() => this.mounted && this.setState({ notFound: true }));
  }

  private run<T>(promise: Promise<T>, then: (value: T) => void): void {
    this.setState({ busy: true, error: '' });
    promise
      .then((v) => this.mounted && then(v))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }))
      .finally(() => this.mounted && this.setState({ busy: false }));
  }

  // ---------------------------------------------------------------- trip form

  private onFormChange = (field: keyof TripInput, value: string): void => {
    this.setState({ form: { ...this.state.form, [field]: value || (field === 'title' || field === 'notes' ? '' : null) } });
  };

  private createTrip = (e: React.FormEvent): void => {
    e.preventDefault();
    this.run(tripsApi.create(this.state.form), (trip) => {
      this.setState({ form: EMPTY_FORM });
      this.props.router.navigate(`/trips/${trip.id}`);
    });
  };

  private startEditing = (): void => {
    const { trip } = this.state;
    if (trip) this.setState({ editing: true, form: { title: trip.title, start_date: trip.start_date, end_date: trip.end_date, notes: trip.notes } });
  };

  private saveTrip = (e: React.FormEvent): void => {
    e.preventDefault();
    const { trip, form } = this.state;
    if (trip) this.run(tripsApi.update(trip.id, form).then(() => tripsApi.get(trip.id)), (t) => this.setState({ trip: t, editing: false, extraDays: 0 }));
  };

  private deleteTrip = (): void => {
    const { trip } = this.state;
    if (trip && window.confirm(this.props.i18n.t('trips.planner.confirmDelete', { title: trip.title })))
      this.run(tripsApi.remove(trip.id), () => this.props.router.navigate('/trips'));
  };

  private renderTripForm(onSubmit: (e: React.FormEvent) => void, submitLabel: string, onCancel?: () => void): React.ReactNode {
    const { t } = this.props.i18n;
    const { form, busy } = this.state;
    return (
      <form onSubmit={onSubmit} className="row g-2 align-items-end">
        <div className="col-md-4">
          <label className="form-label small" htmlFor="trip-title">{t('trips.planner.name')}</label>
          <input id="trip-title" className="form-control" required maxLength={120} value={form.title} placeholder={t('trips.planner.namePlaceholder')} onChange={(e) => this.onFormChange('title', e.target.value)} />
        </div>
        <div className="col-6 col-md-2">
          <label className="form-label small" htmlFor="trip-start">{t('trips.planner.start')}</label>
          <input id="trip-start" type="date" className="form-control" value={form.start_date ?? ''} onChange={(e) => this.onFormChange('start_date', e.target.value)} />
        </div>
        <div className="col-6 col-md-2">
          <label className="form-label small" htmlFor="trip-end">{t('trips.planner.end')}</label>
          <input id="trip-end" type="date" className="form-control" min={form.start_date ?? undefined} value={form.end_date ?? ''} onChange={(e) => this.onFormChange('end_date', e.target.value)} />
        </div>
        {onCancel && (
          <div className="col-12">
            <label className="form-label small" htmlFor="trip-notes">{t('trips.planner.notes')}</label>
            <textarea id="trip-notes" className="form-control" rows={2} value={form.notes ?? ''} onChange={(e) => this.onFormChange('notes', e.target.value)} />
          </div>
        )}
        <div className="col-md-auto d-flex gap-2">
          <button type="submit" className="btn btn-primary" disabled={busy}>{submitLabel}</button>
          {onCancel && <button type="button" className="btn btn-light" onClick={onCancel}>{t('trips.common.cancel')}</button>}
        </div>
      </form>
    );
  }

  // ---------------------------------------------------------------- places search

  private onQuery = (query: string): void => {
    this.setState({ query });
    if (this.searchTimer) clearTimeout(this.searchTimer);
    if (query.trim().length < 2) {
      this.setState({ results: null });
      return;
    }
    this.searchTimer = setTimeout(() => {
      const id = ++this.searchRequest;
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search: query.trim() } })
        .then((r) => this.mounted && id === this.searchRequest && this.setState({ results: r.data.results.slice(0, 8) }))
        .catch(() => this.mounted && id === this.searchRequest && this.setState({ results: [] }));
    }, 300);
  };

  private addStop = (slug: string): void => {
    const { trip, addDay } = this.state;
    if (trip) this.run(tripsApi.addStop(trip.id, slug, addDay).then(() => tripsApi.get(trip.id)), (t) => this.setState({ trip: t }));
  };

  // ---------------------------------------------------------------- stops

  private move = (stops: TripStop[], index: number, delta: -1 | 1): void => {
    const { trip } = this.state;
    const target = index + delta;
    if (!trip || target < 0 || target >= stops.length) return;
    const ids = stops.map((s) => s.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    this.run(tripsApi.reorder(trip.id, stops[index].day, ids), (t) => this.setState({ trip: t }));
  };

  private updateStop = (stop: TripStop, data: Partial<{ day: number; planned_time: string | null; notes: string }>): void => {
    const { trip } = this.state;
    if (trip) this.run(tripsApi.updateStop(trip.id, stop.id, data).then(() => tripsApi.get(trip.id)), (t) => this.setState({ trip: t }));
  };

  private removeStop = (stop: TripStop): void => {
    const { trip } = this.state;
    if (trip) this.run(tripsApi.removeStop(trip.id, stop.id).then(() => tripsApi.get(trip.id)), (t) => this.setState({ trip: t }));
  };

  // ---------------------------------------------------------------- booking links

  /** Book link for a stop: /museums/<slug>?date=YYYY-MM-DD(&slot=<id>), or "date passed" for past dates. */
  private bookTarget(stop: PlannedStop, dayDateIso: string | null): BookTarget {
    const date = stop.visit_date ?? dayDateIso;
    const base = `/museums/${encodeURIComponent(stop.place.slug)}`;
    if (!date) return { date: null, passed: false, url: base };
    if (date < isoDate(0)) return { date, passed: true, url: base };
    const slot = stop.slot_id ? `&slot=${stop.slot_id}` : '';
    return { date, passed: false, url: `${base}?date=${date}${slot}` };
  }

  /** Price per person at a stop: the planned date's price when the API knows it, else the usual starting price. */
  private static stopPrice(stop: PlannedStop): number | null {
    const raw = stop.price_on_date ?? stop.place.starting_price;
    return raw === null || raw === undefined ? null : Number(raw);
  }

  private renderBookAll(trip: Trip): React.ReactNode {
    const { t } = this.props.i18n;
    const stops = (trip.stops as PlannedStop[]).slice().sort((a, b) => a.day - b.day || a.order - b.order);
    const rows = stops.map((stop) => ({
      stop,
      target: this.bookTarget(stop, trip.start_date ? dayDate(trip.start_date, stop.day) : null),
      price: TripPlanner.stopPrice(stop),
    }));
    const bookable = rows.filter((r) => !r.target.passed);
    const priced = bookable.filter((r) => r.price !== null);
    const total = priced.reduce((sum, r) => sum + (r.price ?? 0), 0);
    return (
      <section className="card border-0 shadow-sm mb-4 d-print-none" aria-labelledby="book-all-title">
        <div className="card-body">
          <div className="d-flex align-items-start gap-2 mb-2">
            <h2 id="book-all-title" className="h5 me-auto mb-0">
              <i className="bi bi-ticket-perforated me-2 text-accent" aria-hidden="true" />
              {t('trips.bookAll.title')}
            </h2>
            <button type="button" className="btn-close" aria-label={t('trips.common.close')} onClick={() => this.setState({ showBookAll: false })} />
          </div>
          <p className="small text-muted">{trip.start_date ? t('trips.bookAll.hint') : t('trips.bookAll.noDates')}</p>
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-2">
              <thead className="table-light">
                <tr>
                  <th scope="col">{t('trips.bookAll.colStop')}</th>
                  <th scope="col">{t('trips.bookAll.colDate')}</th>
                  <th scope="col" className="text-end">{t('trips.bookAll.colPrice')}</th>
                  <th scope="col" className="text-end"><span className="visually-hidden">{t('trips.planner.book')}</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ stop, target, price }) => (
                  <tr key={stop.id}>
                    <td>
                      <span className="fw-semibold">{stop.place.name}</span>
                      <div className="small text-muted">{t('trips.planner.day', { n: stop.day })} · {stop.place.city_name}</div>
                    </td>
                    <td className="small">
                      {target.date ? formatDate(target.date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : t('trips.bookAll.noDate')}
                      {stop.planned_time && <span className="text-muted"> · {formatTime(stop.planned_time)}</span>}
                    </td>
                    <td className="text-end small">{price === null ? '–' : price === 0 ? t('common.free') : formatINR(price)}</td>
                    <td className="text-end">
                      {target.passed ? (
                        <span className="badge bg-light text-muted border">{t('trips.planner.datePassed')}</span>
                      ) : (
                        <Link to={target.url} target="_blank" rel="noopener" className="btn btn-sm btn-accent text-nowrap" aria-label={t('trips.bookAll.bookPlace', { name: stop.place.name })}>
                          <i className="bi bi-box-arrow-up-right me-1" aria-hidden="true" />
                          {t('trips.bookAll.book')}
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              {priced.length > 0 && (
                <tfoot>
                  <tr>
                    <th scope="row" colSpan={2}>{t('trips.bookAll.total')}</th>
                    <td className="text-end fw-bold">{formatINR(total)}</td>
                    <td />
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          <p className="small text-muted mb-0">
            {t('trips.bookAll.totalNote')}
            {priced.length < bookable.length && ` ${t('trips.bookAll.unpriced', { n: bookable.length - priced.length })}`}
          </p>
        </div>
      </section>
    );
  }

  // ---------------------------------------------------------------- render

  private renderList(): React.ReactNode {
    const { t } = this.props.i18n;
    const { trips, error } = this.state;
    return (
      <div className="container page py-4 py-lg-5">
        <h1 className="display-6 mb-1">
          <i className="bi bi-signpost-split text-accent me-2" aria-hidden="true" />
          {t('trips.planner.title')}
        </h1>
        <p className="text-muted mb-4">{t('trips.planner.subtitle')}</p>
        <div className="card border-0 shadow-sm mb-4">
          <div className="card-body">
            <h2 className="h6 mb-3">{t('trips.planner.new')}</h2>
            {this.renderTripForm(this.createTrip, t('trips.planner.create'))}
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        {trips === null ? (
          <Loader />
        ) : trips.length === 0 ? (
          <Empty title={t('trips.planner.empty')}>
            <p>{t('trips.planner.emptyHint')}</p>
          </Empty>
        ) : (
          <div className="row g-3">
            {trips.map((trip) => (
              <div key={trip.id} className="col-md-6 col-lg-4">
                <Link to={`/trips/${trip.id}`} className="card border-0 shadow-sm h-100 text-decoration-none text-body">
                  <div className="card-body">
                    <h3 className="h5 mb-1">{trip.title}</h3>
                    <div className="small text-muted mb-2">
                      <i className="bi bi-calendar-event me-1" aria-hidden="true" />
                      {trip.start_date ? `${formatDate(trip.start_date)}${trip.end_date ? ` – ${formatDate(trip.end_date)}` : ''}` : t('trips.planner.noDates')}
                    </div>
                    <span className="badge bg-light text-dark me-1">{t(trip.stop_count === 1 ? 'trips.planner.stops.one' : 'trips.planner.stops.other', { n: trip.stop_count })}</span>
                    {trip.day_count && <span className="badge bg-light text-dark">{t(trip.day_count === 1 ? 'trips.planner.days.one' : 'trips.planner.days.other', { n: trip.day_count })}</span>}
                  </div>
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  private renderStop(stop: TripStop, index: number, stops: TripStop[], date: string | null, dayCount: number): React.ReactNode {
    const { t } = this.props.i18n;
    const { busy } = this.state;
    const p = stop.place;
    const prev = index > 0 ? stops[index - 1].place : null;
    const distance = prev && prev.lat !== null && prev.lng !== null && p.lat !== null && p.lng !== null ? haversineKm(prev.lat, prev.lng, p.lat, p.lng) : null;
    const closed = date !== null && p.closed_weekday !== null && djangoWeekday(date) === p.closed_weekday;
    const target = this.bookTarget(stop as PlannedStop, date);

    return (
      <li key={stop.id} className="list-group-item px-0">
        {distance !== null && (
          <div className="small text-muted mb-2">
            <i className="bi bi-signpost-2 me-1" aria-hidden="true" />
            {t(prev?.approximate || p.approximate ? 'trips.planner.fromPrevApprox' : 'trips.planner.fromPrev', { distance: formatKm(distance) })}
          </div>
        )}
        <div className="d-flex gap-3">
          <div className="flex-shrink-0 rounded-2 overflow-hidden" style={{ width: 72, height: 72, background: museumGradient(p.slug) }}>
            {p.image_url && <img src={sizedImage(p.image_url, 330)} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
          </div>
          <div className="flex-grow-1 min-w-0">
            <div className="d-flex flex-wrap align-items-start gap-2">
              <div className="me-auto">
                <span className="badge bg-primary me-2">{index + 1}</span>
                <Link to={`/museums/${p.slug}`} className="fw-semibold">{p.name}</Link>
                <div className="small text-muted">
                  {t(`common.type.${p.place_type}`)} · {p.city_name}, {p.state_name}
                </div>
                <div className="small">
                  <i className="bi bi-clock me-1" aria-hidden="true" />
                  {formatTime(p.opening_time)} – {formatTime(p.closing_time)}
                  {p.closed_weekday !== null && <span className="text-muted"> · {t('trips.planner.closedOn', { day: t(`common.weekday.${p.closed_weekday}`) })}</span>}
                </div>
                {closed && (
                  <div className="small text-danger fw-semibold">
                    <i className="bi bi-exclamation-triangle me-1" aria-hidden="true" />
                    {t('trips.planner.closedWarning', { day: t(`common.weekday.${p.closed_weekday}`) })}
                  </div>
                )}
                {!p.is_active && <div className="small text-danger">{t('trips.planner.inactive')}</div>}
              </div>
              <div className="btn-group btn-group-sm d-print-none" role="group" aria-label={t('trips.planner.reorder')}>
                <button type="button" className="btn btn-outline-secondary" onClick={() => this.move(stops, index, -1)} disabled={busy || index === 0} aria-label={t('trips.planner.up', { name: p.name })}>
                  <i className="bi bi-arrow-up" aria-hidden="true" />
                </button>
                <button type="button" className="btn btn-outline-secondary" onClick={() => this.move(stops, index, 1)} disabled={busy || index === stops.length - 1} aria-label={t('trips.planner.down', { name: p.name })}>
                  <i className="bi bi-arrow-down" aria-hidden="true" />
                </button>
                <button type="button" className="btn btn-outline-danger" onClick={() => this.removeStop(stop)} disabled={busy} aria-label={t('trips.planner.remove', { name: p.name })}>
                  <i className="bi bi-trash" aria-hidden="true" />
                </button>
              </div>
            </div>
            <div className="row g-2 mt-1 align-items-center">
              <div className="col-6 col-md-3">
                <input
                  type="time"
                  className="form-control form-control-sm"
                  aria-label={t('trips.planner.time', { name: p.name })}
                  defaultValue={stop.planned_time?.slice(0, 5) ?? ''}
                  onBlur={(e) => {
                    const value = e.target.value || null;
                    if (value !== (stop.planned_time?.slice(0, 5) ?? null)) this.updateStop(stop, { planned_time: value });
                  }}
                />
              </div>
              <div className="col-6 col-md-3 d-print-none">
                <select className="form-select form-select-sm" aria-label={t('trips.planner.moveDay', { name: p.name })} value={stop.day} onChange={(e) => this.updateStop(stop, { day: Number(e.target.value) })} disabled={busy}>
                  {Array.from({ length: dayCount }, (_, i) => (
                    <option key={i + 1} value={i + 1}>{t('trips.planner.day', { n: i + 1 })}</option>
                  ))}
                </select>
              </div>
              <div className="col-md">
                <input
                  className="form-control form-control-sm"
                  maxLength={300}
                  placeholder={t('trips.planner.stopNotes')}
                  aria-label={t('trips.planner.stopNotesFor', { name: p.name })}
                  defaultValue={stop.notes}
                  onBlur={(e) => e.target.value !== stop.notes && this.updateStop(stop, { notes: e.target.value })}
                />
              </div>
              <div className="col-md-auto d-print-none">
                {target.passed ? (
                  <span className="btn btn-sm btn-light text-muted w-100 disabled" aria-disabled="true">
                    <i className="bi bi-calendar-x me-1" aria-hidden="true" />
                    {t('trips.planner.datePassed')}
                  </span>
                ) : (
                  <Link to={target.url} className="btn btn-sm btn-accent w-100" title={target.date ? t('trips.planner.bookFor', { date: formatDate(target.date) }) : undefined}>
                    <i className="bi bi-calendar-check me-1" aria-hidden="true" />
                    {t('trips.planner.book')}
                  </Link>
                )}
              </div>
            </div>
          </div>
        </div>
      </li>
    );
  }

  private renderDetail(): React.ReactNode {
    const { t } = this.props.i18n;
    const { trip, notFound, editing, extraDays, query, results, addDay, busy, error, showBookAll } = this.state;
    if (notFound)
      return (
        <div className="container page py-5">
          <Empty title={t('trips.planner.notFound')}>
            <Link to="/trips" className="btn btn-primary">{t('trips.planner.myTrips')}</Link>
          </Empty>
        </div>
      );
    if (!trip) return <Loader />;

    const maxStopDay = trip.stops.reduce((m, s) => Math.max(m, s.day), 1);
    const dayCount = trip.day_count ?? Math.min(MAX_TRIP_DAYS, Math.max(maxStopDay, 1) + extraDays);
    const days = Array.from({ length: dayCount }, (_, i) => i + 1);
    const inTrip = new Set(trip.stops.map((s) => s.place.slug));

    return (
      <div className="container page py-4 py-lg-5">
        <Link to="/trips" className="small d-print-none">
          <i className="bi bi-arrow-left me-1" aria-hidden="true" />
          {t('trips.planner.myTrips')}
        </Link>

        {editing ? (
          <div className="card border-0 shadow-sm my-3">
            <div className="card-body">{this.renderTripForm(this.saveTrip, t('trips.common.save'), () => this.setState({ editing: false }))}</div>
          </div>
        ) : (
          <div className="d-flex flex-wrap align-items-start gap-2 my-3">
            <div className="me-auto">
              <h1 className="display-6 mb-1">{trip.title}</h1>
              <div className="text-muted">
                <i className="bi bi-calendar-event me-1" aria-hidden="true" />
                {trip.start_date ? `${formatDate(trip.start_date)}${trip.end_date ? ` – ${formatDate(trip.end_date)}` : ''}` : t('trips.planner.noDates')}
                {' · '}
                {t(trip.stops.length === 1 ? 'trips.planner.stops.one' : 'trips.planner.stops.other', { n: trip.stops.length })}
              </div>
              {trip.notes && <p className="mt-2 mb-0" style={{ whiteSpace: 'pre-line' }}>{trip.notes}</p>}
            </div>
            <div className="d-flex flex-wrap gap-2 d-print-none">
              {trip.stops.length > 0 && (
                <button type="button" className="btn btn-accent btn-sm" aria-expanded={showBookAll} onClick={() => this.setState({ showBookAll: !showBookAll })}>
                  <i className="bi bi-ticket-perforated me-1" aria-hidden="true" />
                  {t('trips.bookAll.button')}
                </button>
              )}
              <button type="button" className="btn btn-outline-secondary btn-sm" onClick={() => window.print()}>
                <i className="bi bi-printer me-1" aria-hidden="true" />
                {t('trips.planner.print')}
              </button>
              <button type="button" className="btn btn-outline-primary btn-sm" onClick={this.startEditing}>
                <i className="bi bi-pencil me-1" aria-hidden="true" />
                {t('trips.planner.edit')}
              </button>
              <button type="button" className="btn btn-outline-danger btn-sm" onClick={this.deleteTrip} disabled={busy}>
                <i className="bi bi-trash me-1" aria-hidden="true" />
                {t('trips.planner.delete')}
              </button>
            </div>
          </div>
        )}

        {error && <div className="alert alert-danger d-print-none" role="alert">{error}</div>}

        {showBookAll && trip.stops.length > 0 && this.renderBookAll(trip)}

        <div className="card border-0 shadow-sm mb-4 d-print-none">
          <div className="card-body">
            <h2 className="h6">{t('trips.planner.addPlaces')}</h2>
            <div className="row g-2">
              <div className="col-md">
                <div className="input-group">
                  <span className="input-group-text bg-white"><i className="bi bi-search" aria-hidden="true" /></span>
                  <input className="form-control" value={query} onChange={(e) => this.onQuery(e.target.value)} placeholder={t('trips.planner.searchPlaceholder')} aria-label={t('trips.planner.searchPlaceholder')} />
                </div>
              </div>
              <div className="col-md-3">
                <select className="form-select" value={Math.min(addDay, dayCount)} onChange={(e) => this.setState({ addDay: Number(e.target.value) })} aria-label={t('trips.planner.addToDay')}>
                  {days.map((d) => (
                    <option key={d} value={d}>{t('trips.planner.addToDayN', { n: d })}</option>
                  ))}
                </select>
              </div>
            </div>
            {results !== null && (
              <ul className="list-group list-group-flush mt-2" aria-live="polite">
                {results.length === 0 && <li className="list-group-item text-muted small">{t('trips.planner.noResults')}</li>}
                {results.map((m) => (
                  <li key={m.id} className="list-group-item d-flex align-items-center gap-2 px-0">
                    <div className="me-auto">
                      <span className="fw-semibold">{m.name}</span>
                      <span className="small text-muted"> · {m.city_name}, {m.state_name}</span>
                    </div>
                    {inTrip.has(m.slug) && <span className="badge bg-light text-dark">{t('trips.planner.alreadyAdded')}</span>}
                    <button type="button" className="btn btn-sm btn-outline-primary" onClick={() => this.addStop(m.slug)} disabled={busy}>
                      <i className="bi bi-plus-lg me-1" aria-hidden="true" />
                      {t('trips.planner.add')}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {days.map((d) => {
          const stops = trip.stops.filter((s) => s.day === d);
          const date = trip.start_date ? dayDate(trip.start_date, d) : null;
          return (
            <section key={d} className="card border-0 shadow-sm mb-3" style={{ breakInside: 'avoid' }}>
              <div className="card-body">
                <h2 className="h5 mb-2">
                  {t('trips.planner.day', { n: d })}
                  {date && <span className="text-muted fw-normal fs-6 ms-2">{formatDate(date, { weekday: 'long', day: 'numeric', month: 'short' })}</span>}
                </h2>
                {stops.length === 0 ? (
                  <p className="text-muted small mb-0">{t('trips.planner.emptyDay')}</p>
                ) : (
                  <ol className="list-group list-group-flush list-unstyled mb-0">{stops.map((s, i) => this.renderStop(s, i, stops, date, dayCount))}</ol>
                )}
              </div>
            </section>
          );
        })}
        {!trip.day_count && dayCount < MAX_TRIP_DAYS && (
          <button type="button" className="btn btn-outline-secondary btn-sm d-print-none" onClick={() => this.setState({ extraDays: extraDays + 1 })}>
            <i className="bi bi-plus-lg me-1" aria-hidden="true" />
            {t('trips.planner.addDay')}
          </button>
        )}
        <p className="small text-muted mt-3">{t('trips.planner.distanceNote')}</p>
      </div>
    );
  }

  public render(): React.ReactNode {
    return this.tripId ? this.renderDetail() : this.renderList();
  }
}

export default withRouter(withI18n(TripPlanner));
