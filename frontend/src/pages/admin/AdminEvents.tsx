import * as React from 'react';
import { clearApiCache } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import { EVENT_KINDS } from '../../api/events';
import type { AdminEvent, AdminEventPrice, AdminEventSession, EventKind } from '../../api/events';
import { Empty, Loader } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDate, formatINR, formatTime, isoDate } from '../../utils/format';

/*
 * Admin -> Events: events & shows per place, their ticket prices and dated sessions (capacity, on/off).
 * Staff see the events of their places (read only); administrators create and edit.
 */

const KIND_LABELS: Record<EventKind, string> = {
  light_sound: 'Light & sound show',
  night_viewing: 'Night viewing',
  exhibition: 'Exhibition',
  heritage_walk: 'Heritage walk',
  workshop: 'Workshop',
  other: 'Other',
};
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

interface EventForm {
  id: number | null;
  museum: string;
  title: string;
  kind: EventKind;
  description: string;
  image_url: string;
  language: string;
  duration_minutes: string;
  is_active: boolean;
  featured: boolean;
}

interface GenerateForm {
  start_date: string;
  end_date: string;
  start_time: string;
  end_time: string;
  capacity: string;
  weekdays: number[];
}

const emptyEvent = (museum = ''): EventForm => ({
  id: null, museum, title: '', kind: 'light_sound', description: '', image_url: '', language: '',
  duration_minutes: '60', is_active: true, featured: false,
});

const emptyGenerate = (): GenerateForm => ({
  start_date: isoDate(1), end_date: isoDate(14), start_time: '18:30', end_time: '19:30', capacity: '150', weekdays: [],
});

interface AdminEventsState {
  museum: string;
  events: AdminEvent[] | null;
  error: string;
  notice: string;
  form: EventForm | null;
  formError: string;
  saving: boolean;
  selected: AdminEvent | null;
  sessions: AdminEventSession[] | null;
  prices: AdminEventPrice[];
  newPrice: { name: string; price: string };
  gen: GenerateForm;
  busy: boolean;
  panelError: string;
}

class AdminEvents extends React.Component<WithAuthProps, AdminEventsState> {
  public state: AdminEventsState = {
    museum: '', events: null, error: '', notice: '', form: null, formError: '', saving: false,
    selected: null, sessions: null, prices: [], newPrice: { name: '', price: '' }, gen: emptyGenerate(), busy: false, panelError: '',
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private get isAdmin(): boolean {
    return !!this.props.auth.user?.is_admin_role;
  }

  private load = async (): Promise<void> => {
    try {
      const { data } = await api.get<AdminEvent[]>('/admin/events/', { params: { museum: this.state.museum || undefined } });
      if (!this.mounted) return;
      this.setState((s) => ({ events: data, error: '', selected: s.selected ? data.find((e) => e.id === s.selected!.id) ?? null : null }));
    } catch (err) {
      if (this.mounted) this.setState({ events: [], error: errorMessage(err) });
    }
  };

  private loadDetail = async (event: AdminEvent): Promise<void> => {
    this.setState({ selected: event, sessions: null, panelError: '' });
    try {
      const [sessions, prices] = await Promise.all([
        api.get<AdminEventSession[]>('/admin/event-sessions/', { params: { event: event.id, from: isoDate(0) } }),
        api.get<AdminEventPrice[]>('/admin/event-prices/', { params: { event: event.id } }),
      ]);
      if (this.mounted) this.setState({ sessions: sessions.data, prices: prices.data });
    } catch (err) {
      if (this.mounted) this.setState({ sessions: [], panelError: errorMessage(err) });
    }
  };

  private edit(e: AdminEvent): void {
    this.setState({
      formError: '',
      form: {
        id: e.id, museum: e.museum, title: e.title, kind: e.kind, description: e.description, image_url: e.image_url,
        language: e.language, duration_minutes: String(e.duration_minutes), is_active: e.is_active, featured: e.featured,
      },
    });
  }

  private setForm<K extends keyof EventForm>(key: K, value: EventForm[K]): void {
    this.setState((s) => (s.form ? { form: { ...s.form, [key]: value } } : null));
  }

  private save = async (ev: React.FormEvent): Promise<void> => {
    ev.preventDefault();
    const { form } = this.state;
    if (!form) return;
    this.setState({ saving: true, formError: '' });
    const body = { ...form, duration_minutes: Number(form.duration_minutes) || 60 };
    try {
      const { data } = form.id
        ? await api.patch<AdminEvent>(`/admin/events/${form.id}/`, body)
        : await api.post<AdminEvent>('/admin/events/', body);
      await clearApiCache();
      if (!this.mounted) return;
      this.setState({ form: null, notice: form.id ? 'Event saved.' : 'Event created. Add prices and sessions below.' });
      await this.load();
      if (!form.id) this.loadDetail(data);
    } catch (err) {
      if (this.mounted) this.setState({ formError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ saving: false });
    }
  };

  private remove = async (e: AdminEvent): Promise<void> => {
    if (!window.confirm(`Delete "${e.title}" with all its sessions and prices?`)) return;
    try {
      await api.delete(`/admin/events/${e.id}/`);
      await clearApiCache();
      this.setState((s) => ({ notice: 'Event deleted.', selected: s.selected?.id === e.id ? null : s.selected }));
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  /** Runs one change in the sessions/prices panel, then reloads it. */
  private panel = async (run: () => Promise<unknown>, notice = ''): Promise<void> => {
    const { selected } = this.state;
    if (!selected) return;
    this.setState({ busy: true, panelError: '' });
    try {
      await run();
      await clearApiCache();
      if (notice) this.setState({ notice });
      await Promise.all([this.loadDetail(selected), this.load()]);
    } catch (err) {
      if (this.mounted) this.setState({ panelError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  private addPrice = (e: React.FormEvent): void => {
    e.preventDefault();
    const { selected, newPrice, prices } = this.state;
    this.panel(async () => {
      await api.post('/admin/event-prices/', { event: selected!.id, name: newPrice.name, price: newPrice.price || '0', sort: prices.length });
      this.setState({ newPrice: { name: '', price: '' } });
    });
  };

  private generate = (e: React.FormEvent): void => {
    e.preventDefault();
    const { selected, gen } = this.state;
    this.panel(async () => {
      const { data } = await api.post<{ created: number; skipped: number }>(`/admin/events/${selected!.id}/generate-sessions/`, {
        ...gen, capacity: Number(gen.capacity),
      });
      this.setState({ notice: `${data.created} session(s) created${data.skipped ? `, ${data.skipped} already existed` : ''}.` });
    });
  };

  private toggleWeekday(d: number): void {
    this.setState((s) => ({
      gen: { ...s.gen, weekdays: s.gen.weekdays.includes(d) ? s.gen.weekdays.filter((x) => x !== d) : [...s.gen.weekdays, d].sort() },
    }));
  }

  private renderForm(form: EventForm): React.ReactNode {
    const { formError, saving } = this.state;
    return (
      <form className="card border-0 shadow-sm mb-4" onSubmit={this.save}>
        <div className="card-body">
          <h2 className="h5">{form.id ? 'Edit event' : 'New event'}</h2>
          {formError && <div className="alert alert-danger">{formError}</div>}
          <div className="row g-3">
            <div className="col-md-6">
              <MuseumPicker value={form.museum} label="Place" onChange={(slug) => this.setForm('museum', slug)} />
            </div>
            <div className="col-md-6">
              <label htmlFor="ev-title" className="form-label">Title</label>
              <input id="ev-title" className="form-control" value={form.title} maxLength={150} required onChange={(e) => this.setForm('title', e.target.value)} />
            </div>
            <div className="col-md-4">
              <label htmlFor="ev-kind" className="form-label">Type</label>
              <select id="ev-kind" className="form-select" value={form.kind} onChange={(e) => this.setForm('kind', e.target.value as EventKind)}>
                {EVENT_KINDS.map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
              </select>
            </div>
            <div className="col-md-4">
              <label htmlFor="ev-lang" className="form-label">Language(s)</label>
              <input id="ev-lang" className="form-control" value={form.language} maxLength={60} placeholder="Hindi, English" onChange={(e) => this.setForm('language', e.target.value)} />
            </div>
            <div className="col-md-4">
              <label htmlFor="ev-dur" className="form-label">Duration (minutes)</label>
              <input id="ev-dur" type="number" min={1} className="form-control" value={form.duration_minutes} onChange={(e) => this.setForm('duration_minutes', e.target.value)} />
            </div>
            <div className="col-12">
              <label htmlFor="ev-img" className="form-label">Image URL <span className="text-muted">(optional – the place photo is used otherwise)</span></label>
              <input id="ev-img" type="url" className="form-control" value={form.image_url} onChange={(e) => this.setForm('image_url', e.target.value)} />
            </div>
            <div className="col-12">
              <label htmlFor="ev-desc" className="form-label">Description</label>
              <textarea id="ev-desc" className="form-control" rows={4} value={form.description} onChange={(e) => this.setForm('description', e.target.value)} />
            </div>
            <div className="col-12 d-flex gap-4">
              <div className="form-check">
                <input id="ev-active" type="checkbox" className="form-check-input" checked={form.is_active} onChange={(e) => this.setForm('is_active', e.target.checked)} />
                <label htmlFor="ev-active" className="form-check-label">On sale</label>
              </div>
              <div className="form-check">
                <input id="ev-feat" type="checkbox" className="form-check-input" checked={form.featured} onChange={(e) => this.setForm('featured', e.target.checked)} />
                <label htmlFor="ev-feat" className="form-check-label">Featured</label>
              </div>
            </div>
          </div>
          <div className="d-flex gap-2 mt-3">
            <button className="btn btn-primary" disabled={saving || !form.museum}>{saving ? 'Saving…' : 'Save event'}</button>
            <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ form: null })}>Cancel</button>
          </div>
        </div>
      </form>
    );
  }

  private renderPanel(event: AdminEvent): React.ReactNode {
    const { sessions, prices, newPrice, gen, busy, panelError } = this.state;
    const admin = this.isAdmin;
    return (
      <div className="card border-0 shadow-sm mb-4" data-testid="event-panel">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start gap-2 mb-3">
            <div>
              <h2 className="h5 mb-0">{event.title}</h2>
              <div className="small text-muted">{event.museum_name} · {KIND_LABELS[event.kind]}</div>
            </div>
            <button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ selected: null })} />
          </div>
          {panelError && <div className="alert alert-danger">{panelError}</div>}

          <h3 className="h6">Ticket prices</h3>
          <ul className="list-group mb-2">
            {prices.map((p) => (
              <li key={p.id} className="list-group-item d-flex justify-content-between align-items-center">
                <span>{p.name}</span>
                <span className="d-flex align-items-center gap-2">
                  <strong>{Number(p.price) === 0 ? 'Free' : formatINR(p.price)}</strong>
                  {admin && (
                    <button type="button" className="btn btn-sm btn-outline-danger" aria-label={`Remove ${p.name}`} disabled={busy} onClick={() => this.panel(() => api.delete(`/admin/event-prices/${p.id}/`))}>
                      <i className="bi bi-trash" aria-hidden="true" />
                    </button>
                  )}
                </span>
              </li>
            ))}
            {prices.length === 0 && <li className="list-group-item text-muted">No prices yet – visitors can't book until you add one.</li>}
          </ul>
          {admin && (
            <form className="row g-2 mb-4" onSubmit={this.addPrice}>
              <div className="col-sm-6">
                <label htmlFor="np-name" className="visually-hidden">Ticket name</label>
                <input id="np-name" className="form-control form-control-sm" placeholder="Ticket name, e.g. Adult" value={newPrice.name} maxLength={60} required onChange={(e) => this.setState({ newPrice: { ...newPrice, name: e.target.value } })} />
              </div>
              <div className="col-sm-3">
                <label htmlFor="np-price" className="visually-hidden">Price (₹)</label>
                <input id="np-price" type="number" min={0} step="1" className="form-control form-control-sm" placeholder="Price ₹" value={newPrice.price} onChange={(e) => this.setState({ newPrice: { ...newPrice, price: e.target.value } })} />
              </div>
              <div className="col-sm-3">
                <button className="btn btn-sm btn-outline-primary w-100" disabled={busy}>
                  <i className="bi bi-plus-lg me-1" aria-hidden="true" />Add price
                </button>
              </div>
            </form>
          )}

          <h3 className="h6">Upcoming sessions</h3>
          {admin && (
            <form className="border rounded p-2 mb-3 bg-light" onSubmit={this.generate}>
              <div className="small fw-semibold mb-2">Add sessions (one per day in the range)</div>
              <div className="row g-2 align-items-end">
                <div className="col-6 col-md-3">
                  <label htmlFor="g-from" className="form-label small mb-0">From</label>
                  <input id="g-from" type="date" className="form-control form-control-sm" value={gen.start_date} required onChange={(e) => this.setState({ gen: { ...gen, start_date: e.target.value } })} />
                </div>
                <div className="col-6 col-md-3">
                  <label htmlFor="g-to" className="form-label small mb-0">To</label>
                  <input id="g-to" type="date" className="form-control form-control-sm" value={gen.end_date} required onChange={(e) => this.setState({ gen: { ...gen, end_date: e.target.value } })} />
                </div>
                <div className="col-4 col-md-2">
                  <label htmlFor="g-start" className="form-label small mb-0">Starts</label>
                  <input id="g-start" type="time" className="form-control form-control-sm" value={gen.start_time} required onChange={(e) => this.setState({ gen: { ...gen, start_time: e.target.value } })} />
                </div>
                <div className="col-4 col-md-2">
                  <label htmlFor="g-end" className="form-label small mb-0">Ends</label>
                  <input id="g-end" type="time" className="form-control form-control-sm" value={gen.end_time} required onChange={(e) => this.setState({ gen: { ...gen, end_time: e.target.value } })} />
                </div>
                <div className="col-4 col-md-2">
                  <label htmlFor="g-cap" className="form-label small mb-0">Seats</label>
                  <input id="g-cap" type="number" min={1} className="form-control form-control-sm" value={gen.capacity} required onChange={(e) => this.setState({ gen: { ...gen, capacity: e.target.value } })} />
                </div>
                <div className="col-12 d-flex flex-wrap align-items-center gap-2">
                  <span className="small text-muted">Only on:</span>
                  {WEEKDAYS.map((d, i) => (
                    <button key={d} type="button" className={`btn btn-sm ${gen.weekdays.includes(i) ? 'btn-primary' : 'btn-outline-secondary'}`} aria-pressed={gen.weekdays.includes(i)} onClick={() => this.toggleWeekday(i)}>
                      {d}
                    </button>
                  ))}
                  <span className="small text-muted">{gen.weekdays.length === 0 ? '(every day)' : ''}</span>
                  <button className="btn btn-sm btn-primary ms-auto" disabled={busy}>
                    <i className="bi bi-calendar-plus me-1" aria-hidden="true" />Add sessions
                  </button>
                </div>
              </div>
            </form>
          )}
          {sessions === null ? (
            <Loader />
          ) : sessions.length === 0 ? (
            <p className="text-muted">No upcoming sessions.</p>
          ) : (
            <div className="table-responsive" style={{ maxHeight: 420 }}>
              <table className="table table-sm align-middle mb-0">
                <thead className="sticky-top bg-white">
                  <tr><th>Date</th><th>Time</th><th className="text-end">Booked / seats</th><th className="text-end">Waitlist</th><th>Status</th>{admin && <th />}</tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.id} className={s.is_active ? undefined : 'text-muted'}>
                      <td>{formatDate(s.date, { weekday: 'short', day: 'numeric', month: 'short' })}</td>
                      <td>{formatTime(s.start_time)} – {formatTime(s.end_time)}</td>
                      <td className="text-end">{s.booked} / {s.capacity}</td>
                      <td className="text-end">{s.waiting || ''}</td>
                      <td>{s.is_active ? <span className="badge bg-success">On sale</span> : <span className="badge bg-secondary">Off</span>}</td>
                      {admin && (
                        <td className="text-end text-nowrap">
                          <button
                            type="button"
                            className="btn btn-sm btn-outline-secondary me-1"
                            disabled={busy}
                            onClick={() => {
                              const value = window.prompt('Seats for this session', String(s.capacity));
                              if (value && Number(value) > 0) this.panel(() => api.patch(`/admin/event-sessions/${s.id}/`, { capacity: Number(value) }));
                            }}
                          >
                            Seats
                          </button>
                          <button type="button" className="btn btn-sm btn-outline-secondary me-1" disabled={busy} onClick={() => this.panel(() => api.patch(`/admin/event-sessions/${s.id}/`, { is_active: !s.is_active }))}>
                            {s.is_active ? 'Stop sale' : 'Resume'}
                          </button>
                          <button type="button" className="btn btn-sm btn-outline-danger" aria-label="Delete session" disabled={busy} onClick={() => this.panel(() => api.delete(`/admin/event-sessions/${s.id}/`))}>
                            <i className="bi bi-trash" aria-hidden="true" />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { museum, events, error, notice, form, selected } = this.state;
    const admin = this.isAdmin;
    return (
      <div>
        <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
          <h1 className="h3 mb-0">Events & shows</h1>
          {admin && !form && (
            <button type="button" className="btn btn-primary" onClick={() => this.setState({ form: emptyEvent(museum), formError: '' })}>
              <i className="bi bi-plus-lg me-1" aria-hidden="true" />New event
            </button>
          )}
        </div>
        <p className="text-muted small">
          Light & sound shows, night viewings, walks and other ticketed events. Each session has its own seats, separate from the place's entry slots.
          Tickets are paid, cancelled, refunded and checked in like any other booking.
        </p>
        {error && <div className="alert alert-danger">{error}</div>}
        {notice && <div className="alert alert-success alert-dismissible">{notice}<button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ notice: '' })} /></div>}
        {form && this.renderForm(form)}
        <div className="mb-3" style={{ maxWidth: 420 }}>
          <MuseumPicker filter value={museum} label="Filter by place" clearable onChange={(slug) => this.setState({ museum: slug }, this.load)} />
        </div>
        {selected && this.renderPanel(selected)}
        {events === null ? (
          <Loader />
        ) : events.length === 0 ? (
          <Empty title="No events yet." />
        ) : (
          <div className="card border-0 shadow-sm">
            <div className="table-responsive">
              <table className="table table-hover align-middle mb-0">
                <thead>
                  <tr><th>Event</th><th>Place</th><th>Type</th><th className="text-end">Upcoming</th><th>Prices</th><th>Status</th><th /></tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <strong>{e.title}</strong>
                        {e.featured && <span className="badge bg-accent ms-2">Featured</span>}
                      </td>
                      <td>{e.museum_name}</td>
                      <td>{KIND_LABELS[e.kind]}</td>
                      <td className="text-end">{e.upcoming_sessions}</td>
                      <td className="small">{e.prices.map((p) => `${p.name} ${formatINR(p.price)}`).join(', ') || '—'}</td>
                      <td>{e.is_active ? <span className="badge bg-success">On sale</span> : <span className="badge bg-secondary">Hidden</span>}</td>
                      <td className="text-end text-nowrap">
                        <button type="button" className="btn btn-sm btn-outline-primary me-1" onClick={() => this.loadDetail(e)}>Sessions & prices</button>
                        {admin && (
                          <>
                            <button type="button" className="btn btn-sm btn-outline-secondary me-1" onClick={() => this.edit(e)}>Edit</button>
                            <button type="button" className="btn btn-sm btn-outline-danger" aria-label={`Delete ${e.title}`} onClick={() => this.remove(e)}>
                              <i className="bi bi-trash" aria-hidden="true" />
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  }
}

export default withAuth(AdminEvents);
