import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import { clearApiCache } from '../../api/cache';
import type { AdminComboPass, PassOrder } from '../../api/passes';
import type { MuseumSummary, Paginated } from '../../api/types';
import { Empty, Loader } from '../../components/Common';
import { formatDate, formatDateTime, formatINR } from '../../utils/format';
import { placeLocation } from '../../utils/format';

/** Admin: create and edit combo passes (places in visiting order, prices, validity) and see recent pass sales. */

interface Place {
  slug: string;
  name: string;
  city_name: string;
}

interface PassForm {
  id: number | null;
  name: string;
  slug: string;
  description: string;
  image_url: string;
  validity_days: string;
  price_indian: string;
  price_foreign: string;
  price_student: string;
  price_child: string;
  is_active: boolean;
  featured: boolean;
  places: Place[];
}

const emptyForm = (): PassForm => ({
  id: null, name: '', slug: '', description: '', image_url: '', validity_days: '1',
  price_indian: '', price_foreign: '', price_student: '', price_child: '0', is_active: true, featured: false, places: [],
});

const PRICE_FIELDS: { key: 'price_indian' | 'price_foreign' | 'price_student' | 'price_child'; label: string }[] = [
  { key: 'price_indian', label: 'Indian adult' },
  { key: 'price_foreign', label: 'Foreign national' },
  { key: 'price_student', label: 'Student' },
  { key: 'price_child', label: 'Child' },
];

interface AdminPassesState {
  passes: AdminComboPass[] | null;
  orders: PassOrder[];
  ordersCount: number;
  error: string;
  notice: string;
  form: PassForm | null;
  formError: string;
  saving: boolean;
  search: string;
  results: MuseumSummary[];
}

export default class AdminPasses extends React.Component<Record<string, never>, AdminPassesState> {
  public state: AdminPassesState = {
    passes: null, orders: [], ordersCount: 0, error: '', notice: '', form: null, formError: '', saving: false,
    search: '', results: [],
  };

  private mounted = false;
  private searchTimer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.searchTimer);
  }

  private load = async (): Promise<void> => {
    try {
      const [passes, orders] = await Promise.all([
        api.get<AdminComboPass[]>('/admin/passes/'),
        api.get<Paginated<PassOrder>>('/admin/pass-orders/'),
      ]);
      if (this.mounted) {
        this.setState({ passes: passes.data, orders: orders.data.results, ordersCount: orders.data.count, error: '' });
      }
    } catch (err) {
      if (this.mounted) this.setState({ passes: [], error: errorMessage(err) });
    }
  };

  private edit = (p: AdminComboPass): void => {
    this.setState({
      form: {
        id: p.id, name: p.name, slug: p.slug, description: p.description, image_url: p.image_url,
        validity_days: String(p.validity_days), price_indian: p.price_indian, price_foreign: p.price_foreign,
        price_student: p.price_student, price_child: p.price_child, is_active: p.is_active, featured: p.featured,
        places: p.sites.map((s) => ({ slug: s.slug, name: s.name, city_name: s.city_name })),
      },
      formError: '', notice: '', search: '', results: [],
    });
  };

  private newPass = (): void => this.setState({ form: emptyForm(), formError: '', notice: '', search: '', results: [] });

  private setField = <K extends keyof PassForm>(key: K, value: PassForm[K]): void => {
    if (this.state.form) this.setState({ form: { ...this.state.form, [key]: value } });
  };

  private onSearch = (q: string): void => {
    this.setState({ search: q });
    clearTimeout(this.searchTimer);
    if (q.trim().length < 2) {
      this.setState({ results: [] });
      return;
    }
    this.searchTimer = setTimeout(() => {
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search: q.trim() } })
        .then(({ data }) => this.mounted && this.setState({ results: data.results.slice(0, 8) }))
        .catch(() => undefined);
    }, 250);
  };

  private addPlace = (m: MuseumSummary): void => {
    const { form } = this.state;
    if (!form || form.places.some((p) => p.slug === m.slug)) return;
    this.setState({ form: { ...form, places: [...form.places, { slug: m.slug, name: m.name, city_name: m.city_name }] }, search: '', results: [] });
  };

  private movePlace = (index: number, delta: number): void => {
    const { form } = this.state;
    if (!form) return;
    const places = [...form.places];
    const target = index + delta;
    if (target < 0 || target >= places.length) return;
    [places[index], places[target]] = [places[target], places[index]];
    this.setState({ form: { ...form, places } });
  };

  private removePlace = (slug: string): void => {
    const { form } = this.state;
    if (form) this.setState({ form: { ...form, places: form.places.filter((p) => p.slug !== slug) } });
  };

  private save = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { form } = this.state;
    if (!form) return;
    if (form.places.length < 2) {
      this.setState({ formError: 'Add at least two places.' });
      return;
    }
    this.setState({ saving: true, formError: '' });
    const payload = {
      name: form.name.trim(),
      slug: form.slug.trim(),
      description: form.description.trim(),
      image_url: form.image_url.trim(),
      validity_days: Number(form.validity_days),
      price_indian: form.price_indian || '0',
      price_foreign: form.price_foreign || '0',
      price_student: form.price_student || '0',
      price_child: form.price_child || '0',
      is_active: form.is_active,
      featured: form.featured,
      museum_slugs: form.places.map((p) => p.slug),
    };
    try {
      if (form.id) await api.patch(`/admin/passes/${form.id}/`, payload);
      else await api.post('/admin/passes/', payload);
      clearApiCache();
      if (!this.mounted) return;
      this.setState({ form: null, notice: `Saved “${payload.name}”.` });
      this.load();
    } catch (err) {
      if (this.mounted) this.setState({ formError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ saving: false });
    }
  };

  private remove = async (p: AdminComboPass): Promise<void> => {
    if (!window.confirm(`Delete “${p.name}”? Passes that were already bought can only be deactivated.`)) return;
    try {
      await api.delete(`/admin/passes/${p.id}/`);
      clearApiCache();
      if (this.mounted) this.setState({ notice: `Deleted “${p.name}”.`, error: '' });
      this.load();
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err), notice: '' });
    }
  };

  private renderForm(form: PassForm): React.ReactNode {
    const { formError, saving, search, results } = this.state;
    return (
      <form className="card border-0 shadow-sm mb-4" onSubmit={this.save}>
        <div className="card-header bg-white py-3 d-flex justify-content-between align-items-center">
          <h2 className="h5 mb-0">{form.id ? `Edit ${form.name}` : 'New combo pass'}</h2>
          <button type="button" className="btn-close" aria-label="Close form" onClick={() => this.setState({ form: null })} />
        </div>
        <div className="card-body">
          {formError && <div className="alert alert-danger" role="alert">{formError}</div>}
          <div className="row g-3">
            <div className="col-md-6">
              <label htmlFor="pf-name" className="form-label">Name</label>
              <input id="pf-name" className="form-control" value={form.name} onChange={(e) => this.setField('name', e.target.value)} required maxLength={120} />
            </div>
            <div className="col-md-3">
              <label htmlFor="pf-slug" className="form-label">Slug</label>
              <input id="pf-slug" className="form-control" value={form.slug} placeholder="auto" onChange={(e) => this.setField('slug', e.target.value)} maxLength={140} />
            </div>
            <div className="col-md-3">
              <label htmlFor="pf-days" className="form-label">Valid for (days)</label>
              <input id="pf-days" type="number" min={1} max={14} className="form-control" value={form.validity_days} onChange={(e) => this.setField('validity_days', e.target.value)} required />
            </div>
            <div className="col-12">
              <label htmlFor="pf-desc" className="form-label">Description</label>
              <textarea id="pf-desc" className="form-control" rows={2} value={form.description} onChange={(e) => this.setField('description', e.target.value)} />
            </div>
            <div className="col-12">
              <label htmlFor="pf-img" className="form-label">Image URL</label>
              <input id="pf-img" type="url" className="form-control" value={form.image_url} onChange={(e) => this.setField('image_url', e.target.value)} placeholder="https://…" />
            </div>
            {PRICE_FIELDS.map((f) => (
              <div key={f.key} className="col-6 col-md-3">
                <label htmlFor={`pf-${f.key}`} className="form-label">{f.label} (₹)</label>
                <input id={`pf-${f.key}`} type="number" min={0} step="0.01" className="form-control" value={form[f.key]} onChange={(e) => this.setField(f.key, e.target.value)} required />
              </div>
            ))}
            <div className="col-12 d-flex gap-4">
              <div className="form-check">
                <input id="pf-active" type="checkbox" className="form-check-input" checked={form.is_active} onChange={(e) => this.setField('is_active', e.target.checked)} />
                <label htmlFor="pf-active" className="form-check-label">On sale</label>
              </div>
              <div className="form-check">
                <input id="pf-featured" type="checkbox" className="form-check-input" checked={form.featured} onChange={(e) => this.setField('featured', e.target.checked)} />
                <label htmlFor="pf-featured" className="form-check-label">Featured</label>
              </div>
            </div>
            <div className="col-12">
              <span className="form-label d-block">Places (in visiting order)</span>
              {form.places.length === 0 && <p className="text-muted small mb-2">No places yet. Search below to add at least two.</p>}
              <ol className="list-group list-group-numbered mb-2">
                {form.places.map((p, i) => (
                  <li key={p.slug} className="list-group-item d-flex align-items-center gap-2">
                    <span className="flex-grow-1">{p.name} <span className="text-muted small">· {p.city_name}</span></span>
                    <button type="button" className="btn btn-sm btn-light" aria-label={`Move ${p.name} up`} disabled={i === 0} onClick={() => this.movePlace(i, -1)}>
                      <i className="bi bi-arrow-up" aria-hidden="true" />
                    </button>
                    <button type="button" className="btn btn-sm btn-light" aria-label={`Move ${p.name} down`} disabled={i === form.places.length - 1} onClick={() => this.movePlace(i, 1)}>
                      <i className="bi bi-arrow-down" aria-hidden="true" />
                    </button>
                    <button type="button" className="btn btn-sm btn-outline-danger" aria-label={`Remove ${p.name}`} onClick={() => this.removePlace(p.slug)}>
                      <i className="bi bi-x-circle" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ol>
              <div className="position-relative" style={{ maxWidth: 480 }}>
                <input className="form-control" placeholder="Search places to add…" aria-label="Search places to add" value={search} onChange={(e) => this.onSearch(e.target.value)} />
                {results.length > 0 && (
                  <div className="list-group position-absolute w-100 shadow-sm" style={{ zIndex: 5 }}>
                    {results.map((m) => (
                      <button key={m.slug} type="button" className="list-group-item list-group-item-action" onClick={() => this.addPlace(m)}>
                        {m.name} <span className="text-muted small">· {placeLocation(m.city_name, m.state_name)}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="card-footer bg-white d-flex gap-2 justify-content-end">
          <button type="button" className="btn btn-light" onClick={() => this.setState({ form: null })}>Cancel</button>
          <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save pass'}</button>
        </div>
      </form>
    );
  }

  public render(): React.ReactNode {
    const { passes, orders, ordersCount, error, notice, form } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Combo passes</h1>
          {!form && (
            <button className="btn btn-accent" onClick={this.newPass}>
              <i className="bi bi-plus-circle me-1" aria-hidden="true" /> New pass
            </button>
          )}
        </div>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        {notice && <div className="alert alert-success" role="status">{notice}</div>}
        {form && this.renderForm(form)}

        {passes === null ? (
          <Loader />
        ) : passes.length === 0 ? (
          <Empty title="No combo passes yet">
            <p>Run <code>python manage.py seed_passes</code> for three samples, or create one.</p>
          </Empty>
        ) : (
          <div className="card border-0 shadow-sm mb-4">
            <div className="table-responsive">
              <table className="table table-hover align-middle mb-0">
                <thead className="table-light">
                  <tr><th>Pass</th><th>Places</th><th className="text-end">Days</th><th className="text-end">Indian / Foreign / Student / Child</th><th className="text-end">Sold</th><th>Status</th><th /></tr>
                </thead>
                <tbody>
                  {passes.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <div className="fw-semibold">{p.name}</div>
                        <div className="small text-muted">{p.slug}</div>
                      </td>
                      <td className="small">{p.sites.map((s) => s.name).join(' → ')}</td>
                      <td className="text-end">{p.validity_days}</td>
                      <td className="text-end small text-nowrap">
                        {[p.price_indian, p.price_foreign, p.price_student, p.price_child].map((v) => formatINR(v)).join(' / ')}
                      </td>
                      <td className="text-end">{p.orders_count}</td>
                      <td>
                        <span className={`badge ${p.is_active ? 'bg-success' : 'bg-secondary'}`}>{p.is_active ? 'On sale' : 'Hidden'}</span>
                        {p.featured && <span className="badge bg-accent ms-1">Featured</span>}
                      </td>
                      <td className="text-end text-nowrap">
                        <button className="btn btn-sm btn-outline-primary me-1" onClick={() => this.edit(p)} aria-label={`Edit ${p.name}`}>
                          <i className="bi bi-pencil" aria-hidden="true" />
                        </button>
                        <button className="btn btn-sm btn-outline-danger" onClick={() => this.remove(p)} aria-label={`Delete ${p.name}`}>
                          <i className="bi bi-trash" aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <h2 className="h4 mb-3">Recent pass sales <span className="text-muted fs-6">({ordersCount})</span></h2>
        {orders.length === 0 ? (
          <p className="text-muted">No passes sold yet.</p>
        ) : (
          <div className="card border-0 shadow-sm">
            <div className="table-responsive">
              <table className="table table-sm align-middle mb-0">
                <thead className="table-light">
                  <tr><th>Reference</th><th>Pass</th><th>Visitor</th><th>Valid</th><th className="text-end">People</th><th className="text-end">Amount</th><th>Status</th><th>Places used</th></tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.reference}>
                      <td className="ref">{o.reference}</td>
                      <td>{o.pass_name}</td>
                      <td>
                        {o.visitor_name}
                        <div className="small text-muted">{o.user_email}</div>
                      </td>
                      <td className="small text-nowrap">{o.start_date === o.end_date ? formatDate(o.start_date) : `${formatDate(o.start_date)} – ${formatDate(o.end_date)}`}</td>
                      <td className="text-end">{o.total_visitors}</td>
                      <td className="text-end">{formatINR(o.total_amount)}</td>
                      <td><span className="badge bg-light text-dark">{o.status_label}</span></td>
                      <td className="small">
                        {o.sites.filter((s) => s.used).length}/{o.sites.length}
                        {o.paid_at && <div className="text-muted">paid {formatDateTime(o.paid_at)}</div>}
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
