import * as React from 'react';
import { Link } from 'react-router-dom';
import { clearApiCache } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import type { Category, City, MuseumImage, State, TicketType, TimeSlot } from '../../api/types';
import { FACILITY_FLAGS, FACILITY_TEXTS, PHOTOGRAPHY } from '../../api/placeinfo';
import type { AdminClosure, ClosureInput, Facilities, MuseumWithInfo, Photography, PriceRule } from '../../api/placeinfo';
import { Loader } from '../../components/Common';
import { PLACE_TYPES, WEEKDAYS, formatDateTime } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

type FormState = {
  name: string;
  place_type: string;
  state: string;
  city: string;
  category: string;
  tagline: string;
  description: string;
  highlights: string;
  address: string;
  latitude: string;
  longitude: string;
  image_url: string;
  established_year: string;
  managed_by: string;
  contact_phone: string;
  contact_email: string;
  opening_time: string;
  closing_time: string;
  closed_weekday: string;
  is_featured: boolean;
  is_active: boolean;
  allow_groups: boolean;
  school_discount_percent: string;
  group_discount_percent: string;
  info_verified: boolean;
  virtual_tour_url: string;
  virtual_tour_kind: string;
};

const EMPTY: FormState = {
  name: '', place_type: 'museum', state: '', city: '', category: '', tagline: '', description: '', highlights: '', address: '',
  latitude: '', longitude: '', image_url: '', established_year: '', managed_by: '', contact_phone: '',
  contact_email: '', opening_time: '10:00', closing_time: '17:00', closed_weekday: '0', is_featured: false, is_active: true,
  allow_groups: true, school_discount_percent: '25', group_discount_percent: '10', info_verified: false,
  virtual_tour_url: '', virtual_tour_kind: '',
};

const TOUR_KINDS = [
  { value: '', label: 'Detect from the link' },
  { value: '360', label: '360° tour' },
  { value: 'video', label: 'Video' },
  { value: 'google_street_view', label: 'Google Street View' },
  { value: 'other', label: 'Other' },
];

const PHOTO_TYPES = 'image/jpeg,image/png,image/webp';

/** Main photo returned by POST /museums/<slug>/photos/ with make_main. */
interface MainPhotoResult {
  main: true;
  image_url: string;
  image_credit: string;
}

const DEFAULT_TICKETS: TicketType[] = [
  { name: 'Indian Citizen (Adult)', description: 'Indian nationals aged 12+', price: '50', sort_order: 0, is_active: true },
  { name: 'Foreign National', description: '', price: '500', sort_order: 1, is_active: true },
  { name: 'Student', description: 'Valid student ID required', price: '20', sort_order: 2, is_active: true },
  { name: 'Child (below 12)', description: 'Accompanied by an adult', price: '0', sort_order: 3, is_active: true },
];

const hhmm = (t: string) => t.slice(0, 5);

const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const WEEKDAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const emptyClosure = (): ClosureInput => ({ museum: null, start_date: todayIso(), end_date: todayIso(), reason: '', all_day: true, slot_ids: [] });

const emptyRule = (museum: string): PriceRule => ({
  museum, name: '', start_date: null, end_date: null, weekdays: '', ticket_type: null,
  adjustment_type: 'percent', value: '20', priority: 0, is_active: true,
});

interface MuseumFormProps extends WithRouterProps {}

interface MuseumFormState {
  form: FormState;
  tickets: TicketType[];
  slots: TimeSlot[];
  states: State[];
  cities: City[];
  categories: Category[];
  newCity: string;
  loading: boolean;
  error: string;
  saving: boolean;
  /** Who/when the timings & prices were last confirmed (as saved on the server). */
  verifiedSaved: boolean;
  verifiedBy: string | null;
  verifiedAt: string | null;
  images: MuseumImage[];
  imageCredit: string;
  photoFile: File | null;
  photoCaption: string;
  photoCredit: string;
  photoMain: boolean;
  uploading: boolean;
  photoError: string;
  /** Changes the file input's key so it clears after an upload. */
  photoInputKey: number;
  facilities: Facilities;
  closures: AdminClosure[];
  closureDraft: ClosureInput;
  closureError: string;
  closureBusy: boolean;
  rules: PriceRule[];
  ruleDraft: PriceRule | null;
  ruleError: string;
  ruleBusy: boolean;
}

class MuseumFormPage extends React.Component<MuseumFormProps, MuseumFormState> {
  public state: MuseumFormState = {
    form: EMPTY,
    tickets: this.props.router.params.slug ? [] : DEFAULT_TICKETS,
    slots: [],
    states: [],
    cities: [],
    categories: [],
    newCity: '',
    loading: Boolean(this.props.router.params.slug),
    error: '',
    saving: false,
    verifiedSaved: false,
    verifiedBy: null,
    verifiedAt: null,
    images: [],
    imageCredit: '',
    photoFile: null,
    photoCaption: '',
    photoCredit: '',
    photoMain: false,
    uploading: false,
    photoError: '',
    photoInputKey: 0,
    facilities: {},
    closures: [],
    closureDraft: emptyClosure(),
    closureError: '',
    closureBusy: false,
    rules: [],
    ruleDraft: null,
    ruleError: '',
    ruleBusy: false,
  };

  private mounted = false;

  private get slug(): string | undefined {
    return this.props.router.params.slug;
  }

  private get editing(): boolean {
    return Boolean(this.slug);
  }

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
    this.loadCities();
  }

  public componentDidUpdate(prevProps: MuseumFormProps, prevState: MuseumFormState): void {
    if (this.slug !== prevProps.router.params.slug) this.load();
    if (this.state.form.state !== prevState.form.state) this.loadCities();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private load(): void {
    const slug = this.slug;
    api.get<State[]>('/states/').then((r) => {
      if (this.mounted) this.setState({ states: r.data });
    });
    api.get<Category[]>('/categories/').then((r) => {
      if (this.mounted) this.setState({ categories: r.data });
    });
    if (!slug) return;
    this.loadClosures();
    this.loadRules();
    api.get<MuseumWithInfo>(`/museums/${slug}/`).then(({ data: m }) => {
      if (!this.mounted || this.slug !== slug) return;
      this.setState({
        form: {
          name: m.name, place_type: m.place_type, state: String(m.state), city: String(m.city), category: m.category ? String(m.category) : '',
          tagline: m.tagline, description: m.description, highlights: m.highlights, address: m.address,
          latitude: m.latitude ?? '', longitude: m.longitude ?? '', image_url: m.image_url,
          established_year: m.established_year ? String(m.established_year) : '', managed_by: m.managed_by,
          contact_phone: m.contact_phone, contact_email: m.contact_email, opening_time: hhmm(m.opening_time),
          closing_time: hhmm(m.closing_time), closed_weekday: m.closed_weekday === null ? '' : String(m.closed_weekday),
          is_featured: m.is_featured, is_active: m.is_active,
          allow_groups: m.allow_groups ?? true,
          school_discount_percent: String(m.school_discount_percent ?? 25),
          group_discount_percent: String(m.group_discount_percent ?? 10),
          info_verified: Boolean(m.info_verified),
          virtual_tour_url: m.virtual_tour_url ?? '',
          virtual_tour_kind: m.virtual_tour_kind ?? '',
        },
        verifiedSaved: Boolean(m.info_verified),
        verifiedBy: m.info_verified_by_name ?? null,
        verifiedAt: m.info_verified_at ?? null,
        images: m.images ?? [],
        imageCredit: m.image_credit ?? '',
        facilities: m.facilities ?? {},
        tickets: m.ticket_types,
        slots: m.slots.map((s) => ({ ...s, start_time: hhmm(s.start_time), end_time: hhmm(s.end_time) })),
        loading: false,
      });
    });
  }

  private loadCities(): void {
    const stateId = this.state.form.state;
    if (stateId)
      api.get<City[]>('/cities/', { params: { state: stateId } }).then((r) => {
        if (this.mounted && this.state.form.state === stateId) this.setState({ cities: r.data });
      });
    else this.setState({ cities: [] });
  }

  private set = <K extends keyof FormState>(k: K, v: FormState[K]): void => {
    this.setState((s) => ({ form: { ...s.form, [k]: v } }));
  };

  private text = (k: keyof FormState) => ({
    value: this.state.form[k] as string,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => this.set(k, e.target.value),
  });

  private generateSlots = (): void => {
    const { form, slots } = this.state;
    const [oh, om] = form.opening_time.split(':').map(Number);
    const [ch, cm] = form.closing_time.split(':').map(Number);
    const out: TimeSlot[] = [];
    let start = oh * 60 + om;
    const close = ch * 60 + cm;
    const fmt = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
    while (start + 30 <= close) {
      const end = Math.min(close, (Math.floor(start / 60) + 1) * 60);
      out.push({ start_time: fmt(start), end_time: fmt(end), capacity: 100, is_active: true });
      start = end;
    }
    // Keep ids of existing slots that match so bookings stay attached.
    this.setState({ slots: out.map((s) => ({ ...s, id: slots.find((o) => o.start_time === s.start_time)?.id })) });
  };

  private addCity = async (): Promise<void> => {
    const { newCity, form } = this.state;
    if (!newCity.trim() || !form.state) return;
    try {
      const { data } = await api.post<City>('/cities/', { name: newCity.trim(), state: Number(form.state) });
      this.setState((s) => ({ cities: [...s.cities, data].sort((a, b) => a.name.localeCompare(b.name)) }));
      this.set('city', String(data.id));
      this.setState({ newCity: '' });
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { form, tickets, slots } = this.state;
    this.setState({ saving: true, error: '' });
    const payload = {
      name: form.name, place_type: form.place_type, city: Number(form.city), category: form.category ? Number(form.category) : null,
      tagline: form.tagline, description: form.description, highlights: form.highlights, address: form.address,
      latitude: form.latitude || null, longitude: form.longitude || null, image_url: form.image_url,
      established_year: form.established_year ? Number(form.established_year) : null, managed_by: form.managed_by,
      contact_phone: form.contact_phone, contact_email: form.contact_email, opening_time: form.opening_time,
      closing_time: form.closing_time, closed_weekday: form.closed_weekday === '' ? null : Number(form.closed_weekday),
      is_featured: form.is_featured, is_active: form.is_active,
      allow_groups: form.allow_groups,
      school_discount_percent: form.school_discount_percent === '' ? 0 : Number(form.school_discount_percent),
      group_discount_percent: form.group_discount_percent === '' ? 0 : Number(form.group_discount_percent),
      info_verified: form.info_verified,
      virtual_tour_url: form.virtual_tour_url.trim(),
      virtual_tour_kind: form.virtual_tour_url.trim() ? form.virtual_tour_kind : '',
      ticket_types: tickets.map((t, i) => ({ ...t, sort_order: i })),
      slots,
      facilities: this.state.facilities,
    };
    try {
      if (this.editing) await api.put(`/museums/${this.slug}/`, payload);
      else await api.post('/museums/', payload);
      clearApiCache(); // visitors on this device see the change straight away
      this.props.router.navigate('/admin/museums');
    } catch (err) {
      this.setState({ error: errorMessage(err) });
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } finally {
      if (this.mounted) this.setState({ saving: false });
    }
  };

  private uploadPhoto = async (): Promise<void> => {
    const { photoFile, photoCaption, photoCredit, photoMain } = this.state;
    if (!photoFile || !this.slug) return;
    this.setState({ uploading: true, photoError: '' });
    try {
      const body = new FormData();
      body.append('file', photoFile);
      body.append('caption', photoCaption);
      body.append('credit', photoCredit);
      if (photoMain) body.append('make_main', '1');
      const { data } = await api.post<MuseumImage | MainPhotoResult>(`/museums/${this.slug}/photos/`, body);
      if (!this.mounted) return;
      if ('main' in data) {
        this.setState((s) => ({ form: { ...s.form, image_url: data.image_url }, imageCredit: data.image_credit }));
      } else {
        this.setState((s) => ({ images: [...s.images, data] }));
      }
      this.setState((s) => ({ photoFile: null, photoCaption: '', photoCredit: '', photoMain: false, photoInputKey: s.photoInputKey + 1 }));
      clearApiCache();
    } catch (err) {
      if (this.mounted) this.setState({ photoError: errorMessage(err, 'The photo could not be uploaded.') });
    } finally {
      if (this.mounted) this.setState({ uploading: false });
    }
  };

  private deletePhoto = async (img: MuseumImage): Promise<void> => {
    if (!this.slug || !confirm('Remove this photo from the gallery?')) return;
    try {
      await api.delete(`/museums/${this.slug}/photos/${img.id}/`);
      if (this.mounted) this.setState((s) => ({ images: s.images.filter((x) => x.id !== img.id) }));
      clearApiCache();
    } catch (err) {
      if (this.mounted) this.setState({ photoError: errorMessage(err) });
    }
  };

  // ---------------------------------------------------------------- closures calendar

  private loadClosures(): void {
    const slug = this.slug;
    if (!slug) return;
    api.get<AdminClosure[]>('/admin/closures/', { params: { museum: slug, upcoming: 1 } }).then((r) => {
      if (this.mounted && this.slug === slug) this.setState({ closures: r.data });
    }).catch((err) => this.mounted && this.setState({ closureError: errorMessage(err) }));
  }

  private setClosure = (patch: Partial<ClosureInput>): void => this.setState((s) => ({ closureDraft: { ...s.closureDraft, ...patch } }));

  private toggleClosureSlot = (id: number): void =>
    this.setState((s) => {
      const ids = s.closureDraft.slot_ids;
      return { closureDraft: { ...s.closureDraft, slot_ids: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] } };
    });

  private addClosure = async (): Promise<void> => {
    const draft = this.state.closureDraft;
    if (!draft.reason.trim()) {
      this.setState({ closureError: 'Enter a reason visitors will see, e.g. "Annual maintenance".' });
      return;
    }
    this.setState({ closureBusy: true, closureError: '' });
    try {
      await api.post('/admin/closures/', { ...draft, museum: this.slug, reason: draft.reason.trim(), slot_ids: draft.all_day ? [] : draft.slot_ids });
      clearApiCache();
      if (!this.mounted) return;
      this.setState({ closureDraft: emptyClosure() });
      this.loadClosures();
    } catch (err) {
      if (this.mounted) this.setState({ closureError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ closureBusy: false });
    }
  };

  private removeClosure = async (c: AdminClosure): Promise<void> => {
    const msg = c.all_places ? `"${c.reason}" applies to ALL places. Remove it everywhere?` : `Remove the closure "${c.reason}"?`;
    if (!confirm(msg)) return;
    try {
      await api.delete(`/admin/closures/${c.id}/`);
      clearApiCache();
      if (this.mounted) this.setState((s) => ({ closures: s.closures.filter((x) => x.id !== c.id) }));
    } catch (err) {
      if (this.mounted) this.setState({ closureError: errorMessage(err) });
    }
  };

  private renderClosures(): React.ReactNode {
    const { closures, closureDraft: d, closureError, closureBusy, slots } = this.state;
    const savedSlots = slots.filter((s) => s.id);
    const range = (c: AdminClosure) => (c.start_date === c.end_date ? c.start_date : `${c.start_date} → ${c.end_date}`);
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-header bg-white fw-semibold py-3">
          <i className="bi bi-calendar-x text-accent me-2" aria-hidden="true" />Closures
        </div>
        <div className="card-body">
          {!this.editing ? (
            <p className="text-muted small mb-0">Save the place first, then add holidays, maintenance days or slot closures here.</p>
          ) : (
            <>
              {closureError && <div className="alert alert-danger py-2 small">{closureError}</div>}
              {closures.length === 0 ? (
                <p className="text-muted small">No upcoming closures. Visitors can book every open day.</p>
              ) : (
                <div className="table-responsive mb-3">
                  <table className="table table-sm align-middle mb-0">
                    <thead><tr><th>Dates</th><th>Reason</th><th>Closed</th><th /></tr></thead>
                    <tbody>
                      {closures.map((c) => (
                        <tr key={c.id}>
                          <td className="text-nowrap">{range(c)}</td>
                          <td>
                            {c.reason}
                            {c.all_places && <span className="badge bg-light text-dark ms-2">All places</span>}
                          </td>
                          <td className="small">{c.all_day ? 'Whole day' : c.slots.map((s) => hhmm(s.start_time)).join(', ')}</td>
                          <td className="text-end">
                            <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => this.removeClosure(c)} aria-label={`Remove closure ${c.reason}`}>
                              <i className="bi bi-trash" aria-hidden="true" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="border-top pt-3">
                <div className="small fw-semibold mb-2">Add a closure</div>
                <div className="row g-2 align-items-end">
                  <div className="col-6 col-md-3">
                    <label htmlFor="cl-from" className="form-label small mb-1">From</label>
                    <input id="cl-from" type="date" className="form-control form-control-sm" value={d.start_date} onChange={(e) => this.setClosure({ start_date: e.target.value, end_date: d.end_date < e.target.value ? e.target.value : d.end_date })} />
                  </div>
                  <div className="col-6 col-md-3">
                    <label htmlFor="cl-to" className="form-label small mb-1">To</label>
                    <input id="cl-to" type="date" className="form-control form-control-sm" min={d.start_date} value={d.end_date} onChange={(e) => this.setClosure({ end_date: e.target.value })} />
                  </div>
                  <div className="col-md-6">
                    <label htmlFor="cl-reason" className="form-label small mb-1">Reason (shown to visitors)</label>
                    <input id="cl-reason" className="form-control form-control-sm" maxLength={200} placeholder="e.g. Annual maintenance" value={d.reason} onChange={(e) => this.setClosure({ reason: e.target.value })} />
                  </div>
                  <div className="col-12">
                    <div className="form-check form-switch">
                      <input id="cl-allday" className="form-check-input" type="checkbox" checked={d.all_day} onChange={(e) => this.setClosure({ all_day: e.target.checked })} />
                      <label htmlFor="cl-allday" className="form-check-label small">Closed the whole day (switch off to close only some slots)</label>
                    </div>
                  </div>
                  {!d.all_day && (
                    <div className="col-12">
                      {savedSlots.length === 0 ? (
                        <p className="text-muted small mb-0">Save the slots first.</p>
                      ) : (
                        <div className="d-flex flex-wrap gap-3">
                          {savedSlots.map((s) => (
                            <div className="form-check" key={s.id}>
                              <input id={`cl-slot-${s.id}`} className="form-check-input" type="checkbox" checked={d.slot_ids.includes(s.id!)} onChange={() => this.toggleClosureSlot(s.id!)} />
                              <label htmlFor={`cl-slot-${s.id}`} className="form-check-label small">{s.start_time}–{s.end_time}</label>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  <div className="col-12">
                    <button type="button" className="btn btn-primary btn-sm" disabled={closureBusy} onClick={this.addClosure}>
                      <i className="bi bi-plus-lg me-1" aria-hidden="true" />{closureBusy ? 'Adding…' : 'Add closure'}
                    </button>
                  </div>
                </div>
                <p className="form-text mb-0 mt-2">
                  Bookings already made for these dates are not cancelled automatically. National holidays added with <code>manage.py seed_holidays</code> apply to all places; remove any that don't apply.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- seasonal & peak pricing

  private loadRules(): void {
    const slug = this.slug;
    if (!slug) return;
    api.get<PriceRule[]>('/admin/price-rules/', { params: { museum: slug } }).then((r) => {
      if (this.mounted && this.slug === slug) this.setState({ rules: r.data });
    }).catch((err) => this.mounted && this.setState({ ruleError: errorMessage(err) }));
  }

  private updateRule = (index: number | 'draft', patch: Partial<PriceRule>): void => {
    if (index === 'draft') this.setState((s) => ({ ruleDraft: s.ruleDraft ? { ...s.ruleDraft, ...patch } : null }));
    else this.setState((s) => ({ rules: s.rules.map((r, i) => (i === index ? { ...r, ...patch } : r)) }));
  };

  private saveRule = async (rule: PriceRule): Promise<void> => {
    this.setState({ ruleBusy: true, ruleError: '' });
    try {
      const body = { ...rule, museum: this.slug, start_date: rule.start_date || null, end_date: rule.end_date || null };
      if (rule.id) await api.put(`/admin/price-rules/${rule.id}/`, body);
      else await api.post('/admin/price-rules/', body);
      clearApiCache();
      if (!this.mounted) return;
      if (!rule.id) this.setState({ ruleDraft: null });
      this.loadRules();
    } catch (err) {
      if (this.mounted) this.setState({ ruleError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ ruleBusy: false });
    }
  };

  private deleteRule = async (rule: PriceRule): Promise<void> => {
    if (!rule.id || !confirm(`Delete the price rule "${rule.name}"?`)) return;
    try {
      await api.delete(`/admin/price-rules/${rule.id}/`);
      clearApiCache();
      if (this.mounted) this.setState((s) => ({ rules: s.rules.filter((r) => r.id !== rule.id) }));
    } catch (err) {
      if (this.mounted) this.setState({ ruleError: errorMessage(err) });
    }
  };

  private renderRuleRow(rule: PriceRule, index: number | 'draft'): React.ReactNode {
    const { tickets, ruleBusy } = this.state;
    const key = index === 'draft' ? 'new' : String(rule.id);
    const upd = (patch: Partial<PriceRule>) => this.updateRule(index, patch);
    const days = rule.weekdays ? rule.weekdays.split(',') : [];
    const toggleDay = (d: number) => {
      const next = days.includes(String(d)) ? days.filter((x) => x !== String(d)) : [...days, String(d)];
      upd({ weekdays: next.sort().join(',') });
    };
    return (
      <div className="border rounded p-2 mb-2" key={key}>
        <div className="row g-2 align-items-end">
          <div className="col-md-4">
            <label htmlFor={`pr-name-${key}`} className="form-label small mb-1">Name (shown to visitors)</label>
            <input id={`pr-name-${key}`} className="form-control form-control-sm" maxLength={100} placeholder="e.g. Weekend, Diwali week" value={rule.name} onChange={(e) => upd({ name: e.target.value })} />
          </div>
          <div className="col-md-4">
            <label htmlFor={`pr-ticket-${key}`} className="form-label small mb-1">Ticket type</label>
            <select id={`pr-ticket-${key}`} className="form-select form-select-sm" value={rule.ticket_type ?? ''} onChange={(e) => upd({ ticket_type: e.target.value ? Number(e.target.value) : null })}>
              <option value="">All ticket types</option>
              {tickets.filter((t) => t.id).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <div className="col-6 col-md-2">
            <label htmlFor={`pr-kind-${key}`} className="form-label small mb-1">Change</label>
            <select id={`pr-kind-${key}`} className="form-select form-select-sm" value={rule.adjustment_type} onChange={(e) => upd({ adjustment_type: e.target.value as PriceRule['adjustment_type'] })}>
              <option value="percent">Percent ±</option>
              <option value="fixed_price">Fixed price ₹</option>
            </select>
          </div>
          <div className="col-6 col-md-2">
            <label htmlFor={`pr-value-${key}`} className="form-label small mb-1">{rule.adjustment_type === 'percent' ? 'Percent (+/-)' : 'Price (₹)'}</label>
            <input id={`pr-value-${key}`} className="form-control form-control-sm" type="number" step="1" min={rule.adjustment_type === 'percent' ? -100 : 0} value={rule.value} onChange={(e) => upd({ value: e.target.value })} />
          </div>
          <div className="col-6 col-md-3">
            <label htmlFor={`pr-from-${key}`} className="form-label small mb-1">From (optional)</label>
            <input id={`pr-from-${key}`} type="date" className="form-control form-control-sm" value={rule.start_date ?? ''} onChange={(e) => upd({ start_date: e.target.value || null })} />
          </div>
          <div className="col-6 col-md-3">
            <label htmlFor={`pr-to-${key}`} className="form-label small mb-1">To (optional)</label>
            <input id={`pr-to-${key}`} type="date" className="form-control form-control-sm" value={rule.end_date ?? ''} onChange={(e) => upd({ end_date: e.target.value || null })} />
          </div>
          <div className="col-md-4">
            <span className="form-label small mb-1 d-block">Days (none = every day)</span>
            <div className="btn-group btn-group-sm flex-wrap" role="group" aria-label="Weekdays">
              {WEEKDAY_SHORT.map((label, d) => (
                <button key={label} type="button" className={`btn ${days.includes(String(d)) ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={days.includes(String(d))} onClick={() => toggleDay(d)}>{label}</button>
              ))}
            </div>
          </div>
          <div className="col-4 col-md-2">
            <label htmlFor={`pr-prio-${key}`} className="form-label small mb-1">Priority</label>
            <input id={`pr-prio-${key}`} className="form-control form-control-sm" type="number" step="1" value={rule.priority} onChange={(e) => upd({ priority: Number(e.target.value) || 0 })} />
          </div>
          <div className="col-8 col-md-12 d-flex flex-wrap align-items-center gap-2 justify-content-md-end">
            <div className="form-check form-switch me-auto">
              <input id={`pr-on-${key}`} className="form-check-input" type="checkbox" checked={rule.is_active} onChange={(e) => upd({ is_active: e.target.checked })} />
              <label htmlFor={`pr-on-${key}`} className="form-check-label small">Active</label>
            </div>
            <button type="button" className="btn btn-primary btn-sm" disabled={ruleBusy || !rule.name.trim() || rule.value === ''} onClick={() => this.saveRule(rule)}>
              <i className="bi bi-check-lg me-1" aria-hidden="true" />{rule.id ? 'Save rule' : 'Add rule'}
            </button>
            {rule.id ? (
              <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => this.deleteRule(rule)}>Delete</button>
            ) : (
              <button type="button" className="btn btn-light btn-sm" onClick={() => this.setState({ ruleDraft: null })}>Cancel</button>
            )}
          </div>
        </div>
      </div>
    );
  }

  private renderPricing(): React.ReactNode {
    const { rules, ruleDraft, ruleError } = this.state;
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-header bg-white fw-semibold py-3 d-flex justify-content-between align-items-center flex-wrap gap-2">
          <span><i className="bi bi-graph-up text-accent me-2" aria-hidden="true" />Seasonal &amp; peak pricing</span>
          {this.editing && !ruleDraft && (
            <button type="button" className="btn btn-outline-primary btn-sm" onClick={() => this.setState({ ruleDraft: emptyRule(this.slug!) })}>
              <i className="bi bi-plus-lg me-1" aria-hidden="true" /> Add price rule
            </button>
          )}
        </div>
        <div className="card-body">
          {!this.editing ? (
            <p className="text-muted small mb-0">Save the place (and its ticket types) first, then add weekend, festival or season prices here.</p>
          ) : (
            <>
              {ruleError && <div className="alert alert-danger py-2 small">{ruleError}</div>}
              {rules.length === 0 && !ruleDraft && <p className="text-muted small">No price rules: every day uses the ticket prices above.</p>}
              {ruleDraft && this.renderRuleRow(ruleDraft, 'draft')}
              {rules.map((r, i) => this.renderRuleRow(r, i))}
              <p className="form-text mb-0">
                When several active rules match a ticket and date, the highest priority wins. Percent +25 makes tickets 25% dearer, −20 gives 20% off.
                Group and school discounts and GST are worked out on top of the rule price. Bookings already made keep their price.
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- facilities & visitor information

  private setFacility = <K extends keyof Facilities>(key: K, value: Facilities[K]): void =>
    this.setState((s) => {
      const next = { ...s.facilities, [key]: value };
      if (value === '' || value === false || value === undefined) delete next[key];
      return { facilities: next };
    });

  private renderFacilities(): React.ReactNode {
    const f = this.state.facilities;
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-header bg-white fw-semibold py-3">
          <i className="bi bi-info-circle text-accent me-2" aria-hidden="true" />Facilities &amp; visitor information
        </div>
        <div className="card-body">
          <div className="row g-2 mb-3">
            {FACILITY_FLAGS.map((x) => (
              <div className="col-sm-6 col-md-4" key={x.key}>
                <div className="form-check form-switch">
                  <input id={`fa-${x.key}`} className="form-check-input" type="checkbox" checked={Boolean(f[x.key])} onChange={(e) => this.setFacility(x.key, e.target.checked)} />
                  <label htmlFor={`fa-${x.key}`} className="form-check-label">
                    <i className={`bi ${x.icon} me-1`} aria-hidden="true" />{x.label}
                  </label>
                </div>
              </div>
            ))}
          </div>
          <div className="row g-3">
            <div className="col-md-4">
              <label htmlFor="fa-photo" className="form-label">Photography</label>
              <select id="fa-photo" className="form-select" value={f.photography ?? ''} onChange={(e) => this.setFacility('photography', (e.target.value || undefined) as Photography | undefined)}>
                <option value="">Not specified</option>
                {PHOTOGRAPHY.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>
            <div className="col-md-4">
              <label htmlFor="fa-minutes" className="form-label">Average visit (minutes)</label>
              <input id="fa-minutes" className="form-control" type="number" min={1} max={1440} value={f.avg_visit_minutes ?? ''} onChange={(e) => this.setFacility('avg_visit_minutes', e.target.value ? Number(e.target.value) : undefined)} />
            </div>
            {FACILITY_TEXTS.map((x) => (
              <div className={x.key === 'notes' ? 'col-12' : 'col-md-4'} key={x.key}>
                <label htmlFor={`fa-${x.key}`} className="form-label"><i className={`bi ${x.icon} me-1`} aria-hidden="true" />{x.label}</label>
                {x.key === 'notes' ? (
                  <textarea id={`fa-${x.key}`} className="form-control" rows={2} maxLength={1000} value={f[x.key] ?? ''} onChange={(e) => this.setFacility(x.key, e.target.value)} />
                ) : (
                  <input id={`fa-${x.key}`} className="form-control" maxLength={200} value={f[x.key] ?? ''} onChange={(e) => this.setFacility(x.key, e.target.value)} />
                )}
              </div>
            ))}
          </div>
          <p className="form-text mb-0 mt-2">Shown to visitors under "Visitor information". Saved with the place.</p>
        </div>
      </div>
    );
  }

  private renderPhotos(): React.ReactNode {
    const { form, images, imageCredit, photoFile, photoCaption, photoCredit, photoMain, uploading, photoError, photoInputKey } = this.state;
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-header bg-white fw-semibold py-3">
          <i className="bi bi-images text-accent me-2" aria-hidden="true" />Photos
        </div>
        <div className="card-body">
          {!this.editing ? (
            <p className="text-muted small mb-0">Save the place first, then come back here to upload your own photos.</p>
          ) : (
            <>
              {photoError && <div className="alert alert-danger py-2 small">{photoError}</div>}
              <div className="row g-4">
                <div className="col-md-4">
                  <div className="small text-muted mb-1">Main photo</div>
                  {form.image_url ? (
                    <img src={form.image_url} alt={`${form.name} main`} className="img-fluid rounded border" style={{ maxHeight: 180, objectFit: 'cover', width: '100%' }} />
                  ) : (
                    <div className="border rounded bg-light d-flex align-items-center justify-content-center text-muted small" style={{ height: 140 }}>No main photo</div>
                  )}
                  {imageCredit && <div className="form-text">Credit: {imageCredit}</div>}
                </div>
                <div className="col-md-8">
                  <div className="small text-muted mb-1">Gallery ({images.length})</div>
                  {images.length === 0 ? (
                    <p className="text-muted small">No gallery photos yet.</p>
                  ) : (
                    <div className="row g-2">
                      {images.map((img) => (
                        <div className="col-6 col-sm-4 col-lg-3" key={img.id}>
                          <div className="position-relative">
                            <img src={img.url} alt={img.caption || 'Gallery photo'} className="rounded border w-100" style={{ height: 90, objectFit: 'cover' }} loading="lazy" />
                            <button
                              type="button"
                              className="btn btn-sm btn-danger position-absolute top-0 end-0 m-1 py-0 px-1"
                              onClick={() => this.deletePhoto(img)}
                              aria-label={`Delete photo ${img.caption || img.id}`}
                              title="Delete photo"
                            >
                              <i className="bi bi-trash" aria-hidden="true" />
                            </button>
                          </div>
                          {(img.caption || img.credit) && (
                            <div className="small text-muted text-truncate" title={[img.caption, img.credit].filter(Boolean).join(' · ')}>
                              {img.caption || img.credit}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <hr />
              <div className="row g-2 align-items-end">
                <div className="col-md-4">
                  <label htmlFor="mf-photo" className="form-label small mb-1">Upload photo (JPG, PNG or WebP)</label>
                  <input
                    key={photoInputKey}
                    id="mf-photo"
                    type="file"
                    accept={PHOTO_TYPES}
                    className="form-control form-control-sm"
                    onChange={(e) => this.setState({ photoFile: e.target.files?.[0] ?? null })}
                  />
                </div>
                <div className="col-md-3">
                  <label htmlFor="mf-photo-caption" className="form-label small mb-1">Caption</label>
                  <input id="mf-photo-caption" className="form-control form-control-sm" maxLength={200} value={photoCaption} disabled={photoMain} onChange={(e) => this.setState({ photoCaption: e.target.value })} />
                </div>
                <div className="col-md-3">
                  <label htmlFor="mf-photo-credit" className="form-label small mb-1">Credit</label>
                  <input id="mf-photo-credit" className="form-control form-control-sm" maxLength={300} placeholder="Photographer / licence" value={photoCredit} onChange={(e) => this.setState({ photoCredit: e.target.value })} />
                </div>
                <div className="col-md-2">
                  <button type="button" className="btn btn-sm btn-primary w-100" disabled={!photoFile || uploading} onClick={this.uploadPhoto}>
                    <i className="bi bi-upload me-1" aria-hidden="true" />{uploading ? 'Uploading…' : 'Upload'}
                  </button>
                </div>
                <div className="col-12">
                  <div className="form-check">
                    <input id="mf-photo-main" className="form-check-input" type="checkbox" checked={photoMain} onChange={(e) => this.setState({ photoMain: e.target.checked })} />
                    <label htmlFor="mf-photo-main" className="form-check-label small">Set as main photo (replaces the current main photo; otherwise it is added to the gallery)</label>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { form, tickets, slots, states, cities, categories, newCity, loading, error, saving, verifiedSaved, verifiedBy, verifiedAt } = this.state;
    const editing = this.editing;
    const text = this.text;
    const set = this.set;

    if (loading) return <Loader />;

    return (
      <form onSubmit={this.submit}>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">{editing ? `Edit ${form.name}` : 'Add place'}</h1>
          <div className="d-flex gap-2">
            <Link to="/admin/museums" className="btn btn-light">Cancel</Link>
            <button className="btn btn-accent" disabled={saving}>
              <i className="bi bi-check-lg me-1" aria-hidden="true" /> {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}

        <div className="card border-0 shadow-sm mb-4">
          <div className="card-header bg-white fw-semibold py-3">Basic details</div>
          <div className="card-body">
            <div className="row g-3">
              <div className="col-12">
                <label htmlFor="mf-name" className="form-label">Name *</label>
                <input id="mf-name" className="form-control" required {...text('name')} />
              </div>
              <div className="col-md-6">
                <label htmlFor="mf-type" className="form-label">Type of place *</label>
                <select id="mf-type" className="form-select" required {...text('place_type')}>
                  {PLACE_TYPES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </select>
              </div>
              <div className="col-md-6">
                <label htmlFor="mf-state" className="form-label">State / UT *</label>
                <select id="mf-state" className="form-select" required value={form.state} onChange={(e) => { const v = e.target.value; this.setState((s) => ({ form: { ...s.form, state: v, city: '' } })); }}>
                  <option value="">Select…</option>
                  {states.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div className="col-md-6">
                <label htmlFor="mf-city" className="form-label">City *</label>
                <select id="mf-city" className="form-select" required {...text('city')} disabled={!form.state}>
                  <option value="">Select…</option>
                  {cities.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div className="col-md-6">
                <label htmlFor="mf-newcity" className="form-label">New city (if missing)</label>
                <div className="input-group">
                  <input id="mf-newcity" className="form-control" value={newCity} onChange={(e) => this.setState({ newCity: e.target.value })} disabled={!form.state} placeholder="e.g. Khajuraho" />
                  <button type="button" className="btn btn-outline-primary" onClick={this.addCity} disabled={!form.state || !newCity.trim()}>Add</button>
                </div>
              </div>
              <div className="col-md-6">
                <label htmlFor="mf-category" className="form-label">Category</label>
                <select id="mf-category" className="form-select" {...text('category')}>
                  <option value="">—</option>
                  {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div className="col-12">
                <label htmlFor="mf-tagline" className="form-label">Tagline</label>
                <input id="mf-tagline" className="form-control" maxLength={200} {...text('tagline')} />
              </div>
              <div className="col-12">
                <label htmlFor="mf-description" className="form-label">Description *</label>
                <textarea id="mf-description" className="form-control" required rows={5} {...text('description')} />
              </div>
              <div className="col-12">
                <label htmlFor="mf-highlights" className="form-label">Highlights (one per line)</label>
                <textarea id="mf-highlights" className="form-control" rows={4} {...text('highlights')} />
              </div>
              <div className="col-md-4">
                <label htmlFor="mf-year" className="form-label">Established (year)</label>
                <input id="mf-year" className="form-control" type="number" min={1000} max={2100} {...text('established_year')} />
              </div>
              <div className="col-md-4">
                <label htmlFor="mf-managed" className="form-label">Managed by</label>
                <input id="mf-managed" className="form-control" {...text('managed_by')} />
              </div>
              <div className="col-md-4">
                <label htmlFor="mf-image" className="form-label">Image URL</label>
                <input id="mf-image" className="form-control" type="url" placeholder="https://…" {...text('image_url')} />
              </div>
              <div className="col-md-8">
                <label htmlFor="mf-tour" className="form-label">Virtual tour link</label>
                <input id="mf-tour" className="form-control" type="url" placeholder="https://www.youtube.com/watch?v=… or a Google Maps / Arts &amp; Culture link" {...text('virtual_tour_url')} aria-describedby="mf-tour-help" />
                <div id="mf-tour-help" className="form-text">
                  YouTube and Google Maps (Street View) links play inside the place page; other links open in a new tab. Leave empty for none.
                </div>
              </div>
              <div className="col-md-4">
                <label htmlFor="mf-tour-kind" className="form-label">Tour type</label>
                <select id="mf-tour-kind" className="form-select" {...text('virtual_tour_kind')} disabled={!form.virtual_tour_url.trim()}>
                  {TOUR_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                </select>
              </div>
            </div>
          </div>
        </div>

        {this.renderPhotos()}

        <div className="card border-0 shadow-sm mb-4">
          <div className="card-header bg-white fw-semibold py-3">Location, contact &amp; timings</div>
          <div className="card-body">
            <div className="row g-3">
              <div className="col-12">
                <label htmlFor="mf-address" className="form-label">Address *</label>
                <input id="mf-address" className="form-control" required {...text('address')} />
              </div>
              <div className="col-md-6"><label htmlFor="mf-lat" className="form-label">Latitude</label><input id="mf-lat" className="form-control" type="number" step="0.000001" {...text('latitude')} /></div>
              <div className="col-md-6"><label htmlFor="mf-lng" className="form-label">Longitude</label><input id="mf-lng" className="form-control" type="number" step="0.000001" {...text('longitude')} /></div>
              <div className="col-md-6"><label htmlFor="mf-phone" className="form-label">Contact phone</label><input id="mf-phone" className="form-control" {...text('contact_phone')} /></div>
              <div className="col-md-6"><label htmlFor="mf-email" className="form-label">Contact email</label><input id="mf-email" className="form-control" type="email" {...text('contact_email')} /></div>
              <div className="col-md-4"><label htmlFor="mf-opens" className="form-label">Opens *</label><input id="mf-opens" className="form-control" type="time" required {...text('opening_time')} /></div>
              <div className="col-md-4"><label htmlFor="mf-closes" className="form-label">Closes *</label><input id="mf-closes" className="form-control" type="time" required {...text('closing_time')} /></div>
              <div className="col-md-4">
                <label htmlFor="mf-closed" className="form-label">Weekly closed day</label>
                <select id="mf-closed" className="form-select" {...text('closed_weekday')}>
                  <option value="">Open all week</option>
                  {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                </select>
              </div>
            </div>
            <div className="d-flex flex-wrap gap-4 mt-3">
              <div className="form-check form-switch">
                <input id="mf-active" className="form-check-input" type="checkbox" checked={form.is_active} onChange={(e) => set('is_active', e.target.checked)} />
                <label htmlFor="mf-active" className="form-check-label">Active (visible &amp; bookable)</label>
              </div>
              <div className="form-check form-switch">
                <input id="mf-featured" className="form-check-input" type="checkbox" checked={form.is_featured} onChange={(e) => set('is_featured', e.target.checked)} />
                <label htmlFor="mf-featured" className="form-check-label">Featured on home page</label>
              </div>
            </div>
            <div className="border-top mt-3 pt-3">
              <div className="form-check form-switch">
                <input id="mf-verified" className="form-check-input" type="checkbox" checked={form.info_verified} onChange={(e) => set('info_verified', e.target.checked)} />
                <label htmlFor="mf-verified" className="form-check-label">Timings &amp; prices verified with the place</label>
              </div>
              <div className="form-text">
                {form.info_verified && verifiedSaved ? (
                  <>
                    <i className="bi bi-patch-check-fill text-success me-1" aria-hidden="true" />
                    Verified{verifiedBy ? ` by ${verifiedBy}` : ''}{verifiedAt ? ` on ${formatDateTime(verifiedAt)}` : ''}.
                  </>
                ) : form.info_verified ? (
                  'Will be recorded as verified by you when you save.'
                ) : (
                  'Not verified yet: confirm opening hours, closed day and ticket prices with the place (phone, email or official website), then switch this on.'
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="card border-0 shadow-sm mb-4">
          <div className="card-header bg-white fw-semibold py-3 d-flex justify-content-between align-items-center flex-wrap gap-2">
            <span>Ticket types &amp; prices</span>
            <button type="button" className="btn btn-outline-primary btn-sm" onClick={() => this.setState({ tickets: [...tickets, { name: '', description: '', price: '0', sort_order: tickets.length, is_active: true }] })}>
              <i className="bi bi-plus-lg me-1" aria-hidden="true" /> Add ticket type
            </button>
          </div>
          <div className="card-body pt-0">
            {tickets.map((t, i) => {
              const upd = (patch: Partial<TicketType>) => this.setState({ tickets: tickets.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
              return (
                <div className="row g-2 align-items-end py-2 border-bottom" key={t.id ?? `new-${i}`}>
                  <div className="col-md-4"><label className="form-label small mb-1">Name</label><input className="form-control form-control-sm" required value={t.name} onChange={(e) => upd({ name: e.target.value })} /></div>
                  <div className="col-md-4"><label className="form-label small mb-1">Notes</label><input className="form-control form-control-sm" value={t.description} onChange={(e) => upd({ description: e.target.value })} /></div>
                  <div className="col-5 col-md-2"><label className="form-label small mb-1">Price (₹)</label><input className="form-control form-control-sm" type="number" min={0} step="1" required value={t.price} onChange={(e) => upd({ price: e.target.value })} /></div>
                  <div className="col-3 col-md-1">
                    <div className="form-check form-switch mb-1">
                      <input id={`tk-on-${i}`} className="form-check-input" type="checkbox" checked={t.is_active} onChange={(e) => upd({ is_active: e.target.checked })} />
                      <label htmlFor={`tk-on-${i}`} className="form-check-label small">On</label>
                    </div>
                  </div>
                  <div className="col-4 col-md-1 text-end">
                    <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => this.setState({ tickets: tickets.filter((_, j) => j !== i) })}>Remove</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card border-0 shadow-sm mb-4">
          <div className="card-header bg-white fw-semibold py-3">
            <i className="bi bi-people-fill text-accent me-2" aria-hidden="true" />Group bookings
          </div>
          <div className="card-body">
            <div className="form-check form-switch mb-3">
              <input id="mf-groups" className="form-check-input" type="checkbox" checked={form.allow_groups} onChange={(e) => set('allow_groups', e.target.checked)} />
              <label htmlFor="mf-groups" className="form-check-label">Accept group bookings (21–60 people)</label>
            </div>
            <div className="row g-3">
              <div className="col-sm-6 col-md-4">
                <label htmlFor="mf-school-disc" className="form-label">School/college discount %</label>
                <div className="input-group">
                  <input id="mf-school-disc" className="form-control" type="number" min={0} max={100} step={1} required disabled={!form.allow_groups} {...text('school_discount_percent')} />
                  <span className="input-group-text">%</span>
                </div>
              </div>
              <div className="col-sm-6 col-md-4">
                <label htmlFor="mf-group-disc" className="form-label">Other groups discount %</label>
                <div className="input-group">
                  <input id="mf-group-disc" className="form-control" type="number" min={0} max={90} step={1} required disabled={!form.allow_groups} {...text('group_discount_percent')} />
                  <span className="input-group-text">%</span>
                </div>
              </div>
            </div>
            <p className="form-text mb-0 mt-2">
              One ticket and QR covers the whole group. Schools and colleges also get free escorts (teachers). Other groups: tour operators, companies, NGOs.
            </p>
          </div>
        </div>

        <div className="card border-0 shadow-sm mb-4">
          <div className="card-header bg-white fw-semibold py-3 d-flex justify-content-between align-items-center flex-wrap gap-2">
            <span>Entry time slots</span>
            <div className="d-flex flex-wrap gap-2">
              <button type="button" className="btn btn-outline-primary btn-sm" onClick={this.generateSlots}>
                <i className="bi bi-magic me-1" aria-hidden="true" /> Generate hourly from timings
              </button>
              <button type="button" className="btn btn-outline-primary btn-sm" onClick={() => this.setState({ slots: [...slots, { start_time: form.opening_time, end_time: form.closing_time, capacity: 100, is_active: true }] })}>
                <i className="bi bi-plus-lg me-1" aria-hidden="true" /> Add slot
              </button>
            </div>
          </div>
          <div className="card-body pt-0">
            {slots.length === 0 && <p className="text-muted small mt-3 mb-0">No slots yet. Visitors can't book until at least one slot exists.</p>}
            {slots.map((s, i) => {
              const upd = (patch: Partial<TimeSlot>) => this.setState({ slots: slots.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
              return (
                <div className="row g-2 align-items-end py-2 border-bottom" key={s.id ?? `new-${i}`}>
                  <div className="col-6 col-md-3"><label className="form-label small mb-1">Start</label><input className="form-control form-control-sm" type="time" required value={s.start_time} onChange={(e) => upd({ start_time: e.target.value })} /></div>
                  <div className="col-6 col-md-3"><label className="form-label small mb-1">End</label><input className="form-control form-control-sm" type="time" required value={s.end_time} onChange={(e) => upd({ end_time: e.target.value })} /></div>
                  <div className="col-5 col-md-3"><label className="form-label small mb-1">Capacity</label><input className="form-control form-control-sm" type="number" min={1} required value={s.capacity} onChange={(e) => upd({ capacity: Number(e.target.value) })} /></div>
                  <div className="col-3 col-md-1">
                    <div className="form-check form-switch mb-1">
                      <input id={`sl-on-${i}`} className="form-check-input" type="checkbox" checked={s.is_active} onChange={(e) => upd({ is_active: e.target.checked })} />
                      <label htmlFor={`sl-on-${i}`} className="form-check-label small">On</label>
                    </div>
                  </div>
                  <div className="col-4 col-md-2 text-end">
                    <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => this.setState({ slots: slots.filter((_, j) => j !== i) })}>Remove</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {this.renderClosures()}
        {this.renderPricing()}
        {this.renderFacilities()}
      </form>
    );
  }
}

export default withRouter(MuseumFormPage);
