import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { AdminMembershipPlan, Membership } from '../../api/memberships';
import type { MuseumSummary, Paginated } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import { formatDate, formatDateTime, formatINR } from '../../utils/format';
import { placeLocation } from '../../utils/format';

/** Admin: Heritage Card plans (price, discount, places) and the cards sold, with search by email or card number. */

interface Place {
  slug: string;
  name: string;
  city_name: string;
}

interface PlanForm {
  id: number | null;
  name: string;
  slug: string;
  description: string;
  price: string;
  duration_days: string;
  discount_percent: string;
  free_entry: boolean;
  max_visitors_per_booking: string;
  is_active: boolean;
  sort: string;
  places: Place[];
}

const emptyForm = (): PlanForm => ({
  id: null, name: '', slug: '', description: '', price: '', duration_days: '365', discount_percent: '20',
  free_entry: false, max_visitors_per_booking: '1', is_active: true, sort: '0', places: [],
});

const STATUS_BADGE: Record<string, string> = {
  active: 'bg-success', pending: 'bg-warning text-dark', expired: 'bg-secondary', cancelled: 'bg-danger',
};

interface AdminMembershipsState {
  plans: AdminMembershipPlan[] | null;
  cards: Membership[] | null;
  cardsCount: number;
  page: number;
  search: string;
  status: string;
  error: string;
  notice: string;
  form: PlanForm | null;
  formError: string;
  saving: boolean;
  placeSearch: string;
  placeResults: MuseumSummary[];
}

export default class AdminMemberships extends React.Component<Record<string, never>, AdminMembershipsState> {
  public state: AdminMembershipsState = {
    plans: null, cards: null, cardsCount: 0, page: 1, search: '', status: '', error: '', notice: '',
    form: null, formError: '', saving: false, placeSearch: '', placeResults: [],
  };

  private mounted = false;
  private requestId = 0;
  private searchTimer: ReturnType<typeof setTimeout> | undefined;
  private placeTimer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
    this.loadPlans();
    this.loadCards();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.searchTimer);
    clearTimeout(this.placeTimer);
  }

  private loadPlans = (): void => {
    api
      .get<AdminMembershipPlan[]>('/admin/membership-plans/')
      .then(({ data }) => this.mounted && this.setState({ plans: data }))
      .catch((err) => this.mounted && this.setState({ plans: [], error: errorMessage(err) }));
  };

  private loadCards = (): void => {
    const { page, search, status } = this.state;
    const id = ++this.requestId;
    api
      .get<Paginated<Membership>>('/admin/memberships/', { params: { page, search: search.trim() || undefined, status: status || undefined } })
      .then(({ data }) => this.mounted && id === this.requestId && this.setState({ cards: data.results, cardsCount: data.count }))
      .catch((err) => this.mounted && id === this.requestId && this.setState({ cards: [], cardsCount: 0, error: errorMessage(err) }));
  };

  private onSearch = (search: string): void => {
    this.setState({ search, page: 1 });
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(this.loadCards, 300);
  };

  private cancelCard = async (m: Membership): Promise<void> => {
    if (!window.confirm(`Cancel card ${m.card_number} of ${m.holder_name}? The discount stops at once.`)) return;
    const refund = m.paid_at !== null && Number(m.total_amount) > 0
      && window.confirm(`Also refund ${formatINR(m.total_amount)} to the original payment? Press Cancel to keep the money.`);
    try {
      await api.post(`/admin/memberships/${m.card_number}/cancel/`, { refund });
      if (this.mounted) this.setState({ notice: `Cancelled ${m.card_number}${refund ? ' and started the refund' : ''}.`, error: '' });
      this.loadCards();
      this.loadPlans();
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err), notice: '' });
    }
  };

  private edit = (p: AdminMembershipPlan): void => {
    this.setState({
      form: {
        id: p.id, name: p.name, slug: p.slug, description: p.description, price: p.price,
        duration_days: String(p.duration_days), discount_percent: String(p.discount_percent), free_entry: p.free_entry,
        max_visitors_per_booking: String(p.max_visitors_per_booking), is_active: p.is_active, sort: String(p.sort),
        places: p.places.map((m) => ({ slug: m.slug, name: m.name, city_name: m.city_name })),
      },
      formError: '', notice: '', placeSearch: '', placeResults: [],
    });
  };

  private setField = <K extends keyof PlanForm>(key: K, value: PlanForm[K]): void => {
    if (this.state.form) this.setState({ form: { ...this.state.form, [key]: value } });
  };

  private onPlaceSearch = (q: string): void => {
    this.setState({ placeSearch: q });
    clearTimeout(this.placeTimer);
    if (q.trim().length < 2) {
      this.setState({ placeResults: [] });
      return;
    }
    this.placeTimer = setTimeout(() => {
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search: q.trim() } })
        .then(({ data }) => this.mounted && this.setState({ placeResults: data.results.slice(0, 8) }))
        .catch(() => undefined);
    }, 250);
  };

  private addPlace = (m: MuseumSummary): void => {
    const { form } = this.state;
    if (!form || form.places.some((p) => p.slug === m.slug)) return;
    this.setState({ form: { ...form, places: [...form.places, { slug: m.slug, name: m.name, city_name: m.city_name }] }, placeSearch: '', placeResults: [] });
  };

  private removePlace = (slug: string): void => {
    const { form } = this.state;
    if (form) this.setState({ form: { ...form, places: form.places.filter((p) => p.slug !== slug) } });
  };

  private save = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { form } = this.state;
    if (!form) return;
    this.setState({ saving: true, formError: '' });
    const payload = {
      name: form.name.trim(),
      slug: form.slug.trim(),
      description: form.description.trim(),
      price: form.price || '0',
      duration_days: Number(form.duration_days),
      discount_percent: Number(form.discount_percent || 0),
      free_entry: form.free_entry,
      max_visitors_per_booking: Number(form.max_visitors_per_booking),
      is_active: form.is_active,
      sort: Number(form.sort || 0),
      place_slugs: form.places.map((p) => p.slug),
    };
    try {
      if (form.id) await api.patch(`/admin/membership-plans/${form.id}/`, payload);
      else await api.post('/admin/membership-plans/', payload);
      if (!this.mounted) return;
      this.setState({ form: null, notice: `Saved “${payload.name}”.` });
      this.loadPlans();
    } catch (err) {
      if (this.mounted) this.setState({ formError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ saving: false });
    }
  };

  private remove = async (p: AdminMembershipPlan): Promise<void> => {
    if (!window.confirm(`Delete “${p.name}”? Plans with cards sold can only be taken off sale.`)) return;
    try {
      await api.delete(`/admin/membership-plans/${p.id}/`);
      if (this.mounted) this.setState({ notice: `Deleted “${p.name}”.`, error: '' });
      this.loadPlans();
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err), notice: '' });
    }
  };

  private renderForm(form: PlanForm): React.ReactNode {
    const { formError, saving, placeSearch, placeResults } = this.state;
    return (
      <form className="card border-0 shadow-sm mb-4" onSubmit={this.save}>
        <div className="card-header bg-white py-3 d-flex justify-content-between align-items-center">
          <h2 className="h5 mb-0">{form.id ? `Edit ${form.name}` : 'New Heritage Card plan'}</h2>
          <button type="button" className="btn-close" aria-label="Close form" onClick={() => this.setState({ form: null })} />
        </div>
        <div className="card-body">
          {formError && <div className="alert alert-danger" role="alert">{formError}</div>}
          <div className="row g-3">
            <div className="col-md-6">
              <label htmlFor="mp-name" className="form-label">Name</label>
              <input id="mp-name" className="form-control" value={form.name} onChange={(e) => this.setField('name', e.target.value)} required maxLength={100} />
            </div>
            <div className="col-md-3">
              <label htmlFor="mp-slug" className="form-label">Slug</label>
              <input id="mp-slug" className="form-control" value={form.slug} placeholder="auto" onChange={(e) => this.setField('slug', e.target.value)} maxLength={120} />
            </div>
            <div className="col-md-3">
              <label htmlFor="mp-sort" className="form-label">Order</label>
              <input id="mp-sort" type="number" min={0} className="form-control" value={form.sort} onChange={(e) => this.setField('sort', e.target.value)} />
            </div>
            <div className="col-12">
              <label htmlFor="mp-desc" className="form-label">Description</label>
              <textarea id="mp-desc" className="form-control" rows={2} value={form.description} onChange={(e) => this.setField('description', e.target.value)} />
            </div>
            <div className="col-6 col-md-3">
              <label htmlFor="mp-price" className="form-label">Price (₹)</label>
              <input id="mp-price" type="number" min={0} step="0.01" className="form-control" value={form.price} onChange={(e) => this.setField('price', e.target.value)} required />
            </div>
            <div className="col-6 col-md-3">
              <label htmlFor="mp-days" className="form-label">Valid for (days)</label>
              <input id="mp-days" type="number" min={1} className="form-control" value={form.duration_days} onChange={(e) => this.setField('duration_days', e.target.value)} required />
            </div>
            <div className="col-6 col-md-3">
              <label htmlFor="mp-pct" className="form-label">Discount (%)</label>
              <input id="mp-pct" type="number" min={0} max={100} className="form-control" value={form.discount_percent} disabled={form.free_entry} onChange={(e) => this.setField('discount_percent', e.target.value)} />
            </div>
            <div className="col-6 col-md-3">
              <label htmlFor="mp-visitors" className="form-label">Tickets covered per booking</label>
              <input id="mp-visitors" type="number" min={1} className="form-control" value={form.max_visitors_per_booking} onChange={(e) => this.setField('max_visitors_per_booking', e.target.value)} required />
            </div>
            <div className="col-12 d-flex gap-4">
              <div className="form-check">
                <input id="mp-free" type="checkbox" className="form-check-input" checked={form.free_entry} onChange={(e) => this.setField('free_entry', e.target.checked)} />
                <label htmlFor="mp-free" className="form-check-label">Free entry (100% off covered tickets)</label>
              </div>
              <div className="form-check">
                <input id="mp-active" type="checkbox" className="form-check-input" checked={form.is_active} onChange={(e) => this.setField('is_active', e.target.checked)} />
                <label htmlFor="mp-active" className="form-check-label">On sale</label>
              </div>
            </div>
            <div className="col-12">
              <span className="form-label d-block">Places</span>
              {form.places.length === 0 ? (
                <p className="text-muted small mb-2">Valid at all places. Add places below to limit the card to them.</p>
              ) : (
                <div className="d-flex flex-wrap gap-2 mb-2">
                  {form.places.map((p) => (
                    <span key={p.slug} className="badge bg-light text-dark border d-inline-flex align-items-center gap-1">
                      {p.name} <span className="text-muted">· {p.city_name}</span>
                      <button type="button" className="btn btn-sm btn-link p-0 ms-1 text-danger" aria-label={`Remove ${p.name}`} onClick={() => this.removePlace(p.slug)}>
                        <i className="bi bi-x-circle" aria-hidden="true" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="position-relative" style={{ maxWidth: 480 }}>
                <input className="form-control" placeholder="Search places to add…" aria-label="Search places to add" value={placeSearch} onChange={(e) => this.onPlaceSearch(e.target.value)} />
                {placeResults.length > 0 && (
                  <div className="list-group position-absolute w-100 shadow-sm" style={{ zIndex: 5 }}>
                    {placeResults.map((m) => (
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
          <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save plan'}</button>
        </div>
      </form>
    );
  }

  private renderPlans(plans: AdminMembershipPlan[]): React.ReactNode {
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="table-responsive">
          <table className="table table-hover align-middle mb-0">
            <thead className="table-light">
              <tr><th>Plan</th><th className="text-end">Price</th><th>Benefit</th><th>Places</th><th className="text-end">Active cards</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {plans.map((p) => (
                <tr key={p.id}>
                  <td>
                    <div className="fw-semibold">{p.name}</div>
                    <div className="small text-muted">{p.slug} · {p.duration_days} days</div>
                  </td>
                  <td className="text-end">{formatINR(p.price)}</td>
                  <td className="small">
                    {p.free_entry ? 'Free entry' : `${p.discount_percent}% off`} · {p.max_visitors_per_booking} ticket{p.max_visitors_per_booking === 1 ? '' : 's'}/booking
                  </td>
                  <td className="small">{p.all_places ? 'All places' : p.places.map((m) => m.name).join(', ')}</td>
                  <td className="text-end">{p.active_members}</td>
                  <td><span className={`badge ${p.is_active ? 'bg-success' : 'bg-secondary'}`}>{p.is_active ? 'On sale' : 'Hidden'}</span></td>
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
    );
  }

  private renderCards(cards: Membership[]): React.ReactNode {
    const { cardsCount, page } = this.state;
    if (cards.length === 0) return <p className="text-muted">No cards found.</p>;
    return (
      <>
        <div className="card border-0 shadow-sm">
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead className="table-light">
                <tr><th>Card</th><th>Member</th><th>Plan</th><th>Valid</th><th className="text-end">Paid</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {cards.map((m) => (
                  <tr key={m.card_number}>
                    <td className="ref">{m.card_number}</td>
                    <td>
                      {m.holder_name}
                      <div className="small text-muted">{m.user_email}</div>
                    </td>
                    <td className="small">{m.plan_name}</td>
                    <td className="small text-nowrap">{m.starts_on && m.ends_on ? `${formatDate(m.starts_on)} – ${formatDate(m.ends_on)}` : '—'}</td>
                    <td className="text-end small">
                      {formatINR(m.total_amount)}
                      {m.paid_at && <div className="text-muted">{formatDateTime(m.paid_at)}</div>}
                    </td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[m.status] ?? 'bg-light text-dark'}`}>{m.status_label}</span>
                      {m.refund_status && <div className="small text-muted">{m.refund_status_label} {formatINR(m.refund_amount)}</div>}
                    </td>
                    <td className="text-end">
                      {m.status !== 'cancelled' && (
                        <button className="btn btn-sm btn-outline-danger" onClick={() => this.cancelCard(m)} aria-label={`Cancel ${m.card_number}`}>
                          <i className="bi bi-x-octagon me-1" aria-hidden="true" />Cancel
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <Pagination page={page} count={cardsCount} onChange={(p) => this.setState({ page: p }, this.loadCards)} />
      </>
    );
  }

  public render(): React.ReactNode {
    const { plans, cards, cardsCount, error, notice, form, search, status } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Heritage Card</h1>
          {!form && (
            <button className="btn btn-accent" onClick={() => this.setState({ form: emptyForm(), formError: '', notice: '', placeSearch: '', placeResults: [] })}>
              <i className="bi bi-plus-circle me-1" aria-hidden="true" /> New plan
            </button>
          )}
        </div>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        {notice && <div className="alert alert-success" role="status">{notice}</div>}
        {form && this.renderForm(form)}

        <h2 className="h4 mb-3">Plans</h2>
        {plans === null ? (
          <Loader />
        ) : plans.length === 0 ? (
          <Empty title="No plans yet">
            <p>Run <code>python manage.py seed_memberships</code> for the three default plans, or create one.</p>
          </Empty>
        ) : (
          this.renderPlans(plans)
        )}

        <div className="d-flex justify-content-between align-items-end flex-wrap gap-2 mb-3">
          <h2 className="h4 mb-0">Cards sold <span className="text-muted fs-6">({cardsCount})</span></h2>
          <div className="d-flex gap-2">
            <input type="search" className="form-control" style={{ width: 260 }} placeholder="Email or card number…" aria-label="Search cards by email or card number"
              value={search} onChange={(e) => this.onSearch(e.target.value)} />
            <select className="form-select" style={{ width: 150 }} aria-label="Status" value={status}
              onChange={(e) => this.setState({ status: e.target.value, page: 1 }, this.loadCards)}>
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="pending">Pending</option>
              <option value="expired">Expired</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>
        </div>
        {cards === null ? <Loader /> : this.renderCards(cards)}
      </div>
    );
  }
}
