import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { MuseumSummary, Paginated } from '../../api/types';
import {
  APPLIES_TO, DISCOUNT_TYPES, PROMO_SCOPES,
  AppliesTo, DiscountType, GiftVoucher, PromoCode, PromoScope,
} from '../../api/promotions';
import { Empty, Loader, Pagination } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDate, formatDateTime, formatINR, PLACE_TYPES } from '../../utils/format';

/** Admin: promo codes (admins) and gift vouchers (admins + counter staff). */

type Tab = 'promo' | 'voucher';

interface PromoForm {
  id: number | null;
  code: string;
  description: string;
  discount_type: DiscountType;
  value: string;
  max_discount: string;
  min_order_amount: string;
  valid_from: string;
  valid_to: string;
  usage_limit: string;
  per_user_limit: string;
  scope: PromoScope;
  museums: { id: number; name: string }[];
  place_types: string[];
  applies_to: AppliesTo;
  first_booking_only: boolean;
  is_active: boolean;
}

interface VoucherForm {
  initial_value: string;
  purchaser_name: string;
  purchaser_email: string;
  recipient_name: string;
  recipient_email: string;
  message: string;
  valid_until: string;
  send_email: boolean;
}

const emptyPromo = (): PromoForm => ({
  id: null, code: '', description: '', discount_type: 'percent', value: '', max_discount: '', min_order_amount: '0',
  valid_from: '', valid_to: '', usage_limit: '', per_user_limit: '1', scope: 'all', museums: [], place_types: [],
  applies_to: 'both', first_booking_only: false, is_active: true,
});

const emptyVoucher = (): VoucherForm => ({
  initial_value: '', purchaser_name: '', purchaser_email: '', recipient_name: '', recipient_email: '',
  message: '', valid_until: '', send_email: false,
});

/** ISO datetime -> value for <input type="datetime-local"> (local time). */
function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const fromLocalInput = (v: string): string | null => (v ? new Date(v).toISOString() : null);
const numOrNull = (v: string): string | null => (v.trim() === '' ? null : v.trim());

function promoValueLabel(p: PromoCode): string {
  if (p.discount_type === 'flat') return `${formatINR(p.value)} off`;
  const pct = `${Number(p.value)}% off`;
  return p.max_discount ? `${pct} (max ${formatINR(p.max_discount)})` : pct;
}

function promoScopeLabel(p: PromoCode): string {
  if (p.scope === 'museums') return p.museum_names.join(', ') || 'Selected places';
  if (p.scope === 'place_types') {
    return p.place_types.split(',').filter(Boolean)
      .map((t) => PLACE_TYPES.find((x) => x.value === t)?.plural ?? t).join(', ');
  }
  return 'All places';
}

type PromotionsProps = WithAuthProps;

interface PromotionsState {
  tab: Tab;
  error: string;
  notice: string;
  saving: boolean;
  // promo codes
  promos: Paginated<PromoCode> | null;
  promoPage: number;
  promoSearch: string;
  promoForm: PromoForm | null;
  museumSearch: string;
  museumResults: MuseumSummary[];
  // vouchers
  vouchers: Paginated<GiftVoucher> | null;
  voucherPage: number;
  voucherSearch: string;
  voucherForm: VoucherForm | null;
  issued: GiftVoucher | null;
  lookupCode: string;
  lookup: GiftVoucher | null;
  lookupError: string;
}

class PromotionsPage extends React.Component<PromotionsProps, PromotionsState> {
  public state: PromotionsState = {
    tab: this.isAdmin ? 'promo' : 'voucher',
    error: '',
    notice: '',
    saving: false,
    promos: null,
    promoPage: 1,
    promoSearch: '',
    promoForm: null,
    museumSearch: '',
    museumResults: [],
    vouchers: null,
    voucherPage: 1,
    voucherSearch: '',
    voucherForm: null,
    issued: null,
    lookupCode: '',
    lookup: null,
    lookupError: '',
  };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private museumTimer: ReturnType<typeof setTimeout> | undefined;

  private get isAdmin(): boolean {
    return !!this.props.auth.user?.is_admin_role;
  }

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_prev: PromotionsProps, prev: PromotionsState): void {
    const s = this.state;
    if (
      s.tab !== prev.tab || s.promoPage !== prev.promoPage || s.promoSearch !== prev.promoSearch ||
      s.voucherPage !== prev.voucherPage || s.voucherSearch !== prev.voucherSearch
    ) {
      this.scheduleLoad();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
    clearTimeout(this.museumTimer);
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(), 250);
  }

  private load(): void {
    const { tab, promoPage, promoSearch, voucherPage, voucherSearch } = this.state;
    if (tab === 'promo') {
      api
        .get<Paginated<PromoCode>>('/admin/promo-codes/', { params: { page: promoPage, search: promoSearch || undefined } })
        .then((r) => this.mounted && this.setState({ promos: r.data }))
        .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
    } else {
      api
        .get<Paginated<GiftVoucher>>('/admin/gift-vouchers/', { params: { page: voucherPage, search: voucherSearch || undefined } })
        .then((r) => this.mounted && this.setState({ vouchers: r.data }))
        .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
    }
  }

  // ---------------------------------------------------------------- promo codes

  private editPromo(p: PromoCode): void {
    this.setState({
      error: '', notice: '',
      promoForm: {
        id: p.id, code: p.code, description: p.description, discount_type: p.discount_type, value: p.value,
        max_discount: p.max_discount ?? '', min_order_amount: p.min_order_amount,
        valid_from: toLocalInput(p.valid_from), valid_to: toLocalInput(p.valid_to),
        usage_limit: p.usage_limit === null ? '' : String(p.usage_limit),
        per_user_limit: p.per_user_limit === null ? '' : String(p.per_user_limit),
        scope: p.scope, museums: p.museums.map((id, i) => ({ id, name: p.museum_names[i] ?? `#${id}` })),
        place_types: p.place_types.split(',').filter(Boolean), applies_to: p.applies_to,
        first_booking_only: p.first_booking_only, is_active: p.is_active,
      },
    });
  }

  private setPromo = <K extends keyof PromoForm>(key: K, value: PromoForm[K]): void => {
    this.setState((s) => ({ promoForm: s.promoForm && { ...s.promoForm, [key]: value } }));
  };

  private searchMuseums = (q: string): void => {
    this.setState({ museumSearch: q });
    clearTimeout(this.museumTimer);
    if (!q.trim()) {
      this.setState({ museumResults: [] });
      return;
    }
    this.museumTimer = setTimeout(() => {
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search: q } })
        .then((r) => this.mounted && this.setState({ museumResults: r.data.results }))
        .catch(() => undefined);
    }, 250);
  };

  private savePromo = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const f = this.state.promoForm;
    if (!f) return;
    const body = {
      code: f.code, description: f.description, discount_type: f.discount_type, value: f.value,
      max_discount: f.discount_type === 'percent' ? numOrNull(f.max_discount) : null,
      min_order_amount: f.min_order_amount || '0',
      valid_from: fromLocalInput(f.valid_from), valid_to: fromLocalInput(f.valid_to),
      usage_limit: numOrNull(f.usage_limit), per_user_limit: numOrNull(f.per_user_limit),
      scope: f.scope, museums: f.scope === 'museums' ? f.museums.map((m) => m.id) : [],
      place_types: f.scope === 'place_types' ? f.place_types.join(',') : '',
      applies_to: f.applies_to, first_booking_only: f.first_booking_only, is_active: f.is_active,
    };
    this.setState({ saving: true, error: '' });
    try {
      if (f.id) await api.put(`/admin/promo-codes/${f.id}/`, body);
      else await api.post('/admin/promo-codes/', body);
      this.setState({ promoForm: null, saving: false, notice: `Promo code ${f.code.toUpperCase()} saved.` });
      this.load();
    } catch (err) {
      this.setState({ saving: false, error: errorMessage(err) });
    }
  };

  private togglePromo = async (p: PromoCode): Promise<void> => {
    try {
      await api.patch(`/admin/promo-codes/${p.id}/`, { is_active: !p.is_active });
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private deletePromo = async (p: PromoCode): Promise<void> => {
    if (!window.confirm(`Delete promo code ${p.code}?`)) return;
    try {
      await api.delete(`/admin/promo-codes/${p.id}/`);
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private renderPromoForm(f: PromoForm): React.ReactNode {
    const { saving, museumSearch, museumResults } = this.state;
    return (
      <form className="card border-0 shadow-sm mb-4" onSubmit={this.savePromo}>
        <div className="card-body p-4">
          <h2 className="h5 mb-3">{f.id ? `Edit ${f.code}` : 'New promo code'}</h2>
          <div className="row g-3">
            <div className="col-md-4">
              <label className="form-label">Code</label>
              <input className="form-control text-uppercase" required maxLength={30} value={f.code}
                onChange={(e) => this.setPromo('code', e.target.value)} placeholder="e.g. DIWALI20" />
            </div>
            <div className="col-md-8">
              <label className="form-label">Description</label>
              <input className="form-control" maxLength={200} value={f.description}
                onChange={(e) => this.setPromo('description', e.target.value)} />
            </div>
            <div className="col-md-3">
              <label className="form-label">Discount type</label>
              <select className="form-select" value={f.discount_type} onChange={(e) => this.setPromo('discount_type', e.target.value as DiscountType)}>
                {DISCOUNT_TYPES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </div>
            <div className="col-md-3">
              <label className="form-label">{f.discount_type === 'percent' ? 'Percent' : 'Amount (₹)'}</label>
              <input type="number" className="form-control" required min="0.01" step="0.01" max={f.discount_type === 'percent' ? 100 : undefined}
                value={f.value} onChange={(e) => this.setPromo('value', e.target.value)} />
            </div>
            {f.discount_type === 'percent' && (
              <div className="col-md-3">
                <label className="form-label">Max discount (₹)</label>
                <input type="number" className="form-control" min="0" step="1" value={f.max_discount} placeholder="No cap"
                  onChange={(e) => this.setPromo('max_discount', e.target.value)} />
              </div>
            )}
            <div className="col-md-3">
              <label className="form-label">Min order (₹)</label>
              <input type="number" className="form-control" min="0" step="1" value={f.min_order_amount}
                onChange={(e) => this.setPromo('min_order_amount', e.target.value)} />
            </div>
            <div className="col-md-3">
              <label className="form-label">Valid from</label>
              <input type="datetime-local" className="form-control" value={f.valid_from} onChange={(e) => this.setPromo('valid_from', e.target.value)} />
            </div>
            <div className="col-md-3">
              <label className="form-label">Valid to</label>
              <input type="datetime-local" className="form-control" value={f.valid_to} onChange={(e) => this.setPromo('valid_to', e.target.value)} />
            </div>
            <div className="col-md-3">
              <label className="form-label">Total uses</label>
              <input type="number" className="form-control" min="1" step="1" value={f.usage_limit} placeholder="Unlimited"
                onChange={(e) => this.setPromo('usage_limit', e.target.value)} />
            </div>
            <div className="col-md-3">
              <label className="form-label">Uses per visitor</label>
              <input type="number" className="form-control" min="1" step="1" value={f.per_user_limit} placeholder="Unlimited"
                onChange={(e) => this.setPromo('per_user_limit', e.target.value)} />
            </div>
            <div className="col-md-4">
              <label className="form-label">Valid at</label>
              <select className="form-select" value={f.scope} onChange={(e) => this.setPromo('scope', e.target.value as PromoScope)}>
                {PROMO_SCOPES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </div>
            <div className="col-md-4">
              <label className="form-label">Booking type</label>
              <select className="form-select" value={f.applies_to} onChange={(e) => this.setPromo('applies_to', e.target.value as AppliesTo)}>
                {APPLIES_TO.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </div>
            <div className="col-md-4 d-flex flex-column justify-content-end gap-1">
              <div className="form-check">
                <input id="pf-first" type="checkbox" className="form-check-input" checked={f.first_booking_only}
                  onChange={(e) => this.setPromo('first_booking_only', e.target.checked)} />
                <label htmlFor="pf-first" className="form-check-label">First booking only</label>
              </div>
              <div className="form-check">
                <input id="pf-active" type="checkbox" className="form-check-input" checked={f.is_active}
                  onChange={(e) => this.setPromo('is_active', e.target.checked)} />
                <label htmlFor="pf-active" className="form-check-label">Active</label>
              </div>
            </div>
            {f.scope === 'place_types' && (
              <div className="col-12">
                <label className="form-label d-block">Place types</label>
                {PLACE_TYPES.map((t) => (
                  <div key={t.value} className="form-check form-check-inline">
                    <input id={`pt-${t.value}`} type="checkbox" className="form-check-input" checked={f.place_types.includes(t.value)}
                      onChange={(e) => this.setPromo('place_types', e.target.checked
                        ? [...f.place_types, t.value] : f.place_types.filter((x) => x !== t.value))} />
                    <label htmlFor={`pt-${t.value}`} className="form-check-label">{t.plural}</label>
                  </div>
                ))}
              </div>
            )}
            {f.scope === 'museums' && (
              <div className="col-12">
                <label className="form-label">Places</label>
                <div className="d-flex flex-wrap gap-2 mb-2">
                  {f.museums.length === 0 && <span className="text-muted small">No places picked yet.</span>}
                  {f.museums.map((m) => (
                    <span key={m.id} className="badge bg-primary d-inline-flex align-items-center gap-1">
                      {m.name}
                      <button type="button" className="btn btn-sm btn-link text-white p-0 ms-1" aria-label={`Remove ${m.name}`}
                        onClick={() => this.setPromo('museums', f.museums.filter((x) => x.id !== m.id))}>
                        <i className="bi bi-x-circle" aria-hidden="true" />
                      </button>
                    </span>
                  ))}
                </div>
                <input className="form-control" placeholder="Search places to add…" value={museumSearch}
                  onChange={(e) => this.searchMuseums(e.target.value)} />
                {museumResults.length > 0 && (
                  <div className="list-group mt-1">
                    {museumResults.filter((m) => !f.museums.some((x) => x.id === m.id)).map((m) => (
                      <button key={m.id} type="button" className="list-group-item list-group-item-action"
                        onClick={() => {
                          this.setPromo('museums', [...f.museums, { id: m.id, name: m.name }]);
                          this.setState({ museumSearch: '', museumResults: [] });
                        }}>
                        <i className="bi bi-plus-lg me-2" aria-hidden="true" />{m.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="d-flex gap-2 mt-4">
            <button type="submit" className="btn btn-accent" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
            <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ promoForm: null })}>Cancel</button>
          </div>
        </div>
      </form>
    );
  }

  private renderPromos(): React.ReactNode {
    const { promos, promoForm, promoSearch, promoPage } = this.state;
    return (
      <>
        {promoForm ? this.renderPromoForm(promoForm) : (
          <div className="d-flex flex-wrap gap-2 mb-3">
            <input className="form-control" style={{ maxWidth: 280 }} placeholder="Search codes…" value={promoSearch}
              onChange={(e) => this.setState({ promoSearch: e.target.value, promoPage: 1 })} />
            <button className="btn btn-accent ms-auto" onClick={() => this.setState({ promoForm: emptyPromo(), notice: '', error: '' })}>
              <i className="bi bi-plus-lg me-1" aria-hidden="true" />New promo code
            </button>
          </div>
        )}
        {!promos ? <Loader /> : promos.results.length === 0 ? <Empty title="No promo codes yet" /> : (
          <div className="card border-0 shadow-sm">
            <div className="table-responsive">
              <table className="table table-hover align-middle mb-0">
                <thead className="table-light">
                  <tr><th>Code</th><th>Discount</th><th>Valid at</th><th>Validity</th><th className="text-end">Used</th><th className="text-end">Given</th><th>Status</th><th /></tr>
                </thead>
                <tbody>
                  {promos.results.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <strong className="font-monospace">{p.code}</strong>
                        {p.description && <div className="small text-muted">{p.description}</div>}
                      </td>
                      <td>
                        {promoValueLabel(p)}
                        {Number(p.min_order_amount) > 0 && <div className="small text-muted">Min {formatINR(p.min_order_amount)}</div>}
                      </td>
                      <td className="small">
                        {promoScopeLabel(p)}
                        <div className="text-muted">
                          {APPLIES_TO.find((a) => a.value === p.applies_to)?.label}
                          {p.first_booking_only && ' · first booking'}
                        </div>
                      </td>
                      <td className="small">
                        {p.valid_from ? formatDateTime(p.valid_from) : 'Now'} – {p.valid_to ? formatDateTime(p.valid_to) : 'No end'}
                      </td>
                      <td className="text-end">
                        {p.uses_count}{p.usage_limit !== null && ` / ${p.usage_limit}`}
                      </td>
                      <td className="text-end">{formatINR(p.total_discount)}</td>
                      <td>
                        <span className={`badge ${p.is_active ? 'bg-success' : 'bg-secondary'}`}>{p.is_active ? 'Active' : 'Inactive'}</span>
                      </td>
                      <td className="text-end text-nowrap">
                        <button className="btn btn-sm btn-outline-primary me-1" title="Edit" onClick={() => this.editPromo(p)}>
                          <i className="bi bi-pencil" aria-hidden="true" />
                        </button>
                        <button className="btn btn-sm btn-outline-secondary me-1" title={p.is_active ? 'Deactivate' : 'Activate'} onClick={() => this.togglePromo(p)}>
                          <i className={`bi ${p.is_active ? 'bi-slash-circle' : 'bi-check-circle'}`} aria-hidden="true" />
                        </button>
                        {p.uses_count === 0 && (
                          <button className="btn btn-sm btn-outline-danger" title="Delete" onClick={() => this.deletePromo(p)}>
                            <i className="bi bi-trash" aria-hidden="true" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {promos && <Pagination page={promoPage} count={promos.count} onChange={(promoPage: number) => this.setState({ promoPage })} />}
      </>
    );
  }

  // ---------------------------------------------------------------- gift vouchers

  private setVoucher = <K extends keyof VoucherForm>(key: K, value: VoucherForm[K]): void => {
    this.setState((s) => ({ voucherForm: s.voucherForm && { ...s.voucherForm, [key]: value } }));
  };

  private issueVoucher = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const f = this.state.voucherForm;
    if (!f) return;
    const body: Record<string, unknown> = { ...f };
    if (!f.valid_until) delete body.valid_until;
    this.setState({ saving: true, error: '' });
    try {
      const { data } = await api.post<GiftVoucher>('/admin/gift-vouchers/', body);
      this.setState({
        voucherForm: null, saving: false, issued: data,
        notice: f.send_email ? `Voucher issued and emailed to ${data.recipient_email}.` : 'Voucher issued.',
      });
      this.load();
    } catch (err) {
      this.setState({ saving: false, error: errorMessage(err) });
    }
  };

  private deactivateVoucher = async (v: GiftVoucher): Promise<void> => {
    if (!window.confirm(`Deactivate voucher ${v.code}? It can no longer be used.`)) return;
    try {
      await api.post(`/admin/gift-vouchers/${v.id}/deactivate/`);
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private emailVoucher = async (v: GiftVoucher): Promise<void> => {
    try {
      const { data } = await api.post<{ sent: boolean }>(`/admin/gift-vouchers/${v.id}/send-email/`);
      this.setState({ notice: data.sent ? `Voucher emailed to ${v.recipient_email}.` : 'The email could not be sent.' });
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private doLookup = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const code = this.state.lookupCode.trim();
    if (!code) return;
    this.setState({ lookup: null, lookupError: '' });
    try {
      const { data } = await api.get<GiftVoucher>('/admin/gift-vouchers/lookup/', { params: { code } });
      this.setState({ lookup: data });
    } catch (err) {
      this.setState({ lookupError: errorMessage(err) });
    }
  };

  private voucherStatus(v: GiftVoucher): React.ReactNode {
    if (!v.is_active) return <span className="badge bg-secondary">Deactivated</span>;
    if (v.is_expired) return <span className="badge bg-danger">Expired</span>;
    if (Number(v.balance) <= 0) return <span className="badge bg-dark">Used up</span>;
    return <span className="badge bg-success">Active</span>;
  }

  private renderVoucherForm(f: VoucherForm): React.ReactNode {
    const { saving } = this.state;
    return (
      <form className="card border-0 shadow-sm mb-4" onSubmit={this.issueVoucher}>
        <div className="card-body p-4">
          <h2 className="h5 mb-3">Issue gift voucher</h2>
          <div className="row g-3">
            <div className="col-md-4">
              <label className="form-label">Value (₹)</label>
              <input type="number" className="form-control" required min="1" step="1" value={f.initial_value}
                onChange={(e) => this.setVoucher('initial_value', e.target.value)} />
            </div>
            <div className="col-md-4">
              <label className="form-label">Valid until</label>
              <input type="date" className="form-control" value={f.valid_until} onChange={(e) => this.setVoucher('valid_until', e.target.value)} />
              <div className="form-text">Leave empty for 1 year.</div>
            </div>
            <div className="col-md-6">
              <label className="form-label">Purchaser name</label>
              <input className="form-control" maxLength={120} value={f.purchaser_name} onChange={(e) => this.setVoucher('purchaser_name', e.target.value)} />
            </div>
            <div className="col-md-6">
              <label className="form-label">Purchaser email</label>
              <input type="email" className="form-control" value={f.purchaser_email} onChange={(e) => this.setVoucher('purchaser_email', e.target.value)} />
            </div>
            <div className="col-md-6">
              <label className="form-label">Recipient name</label>
              <input className="form-control" maxLength={120} value={f.recipient_name} onChange={(e) => this.setVoucher('recipient_name', e.target.value)} />
            </div>
            <div className="col-md-6">
              <label className="form-label">Recipient email</label>
              <input type="email" className="form-control" value={f.recipient_email} onChange={(e) => this.setVoucher('recipient_email', e.target.value)} />
            </div>
            <div className="col-12">
              <label className="form-label">Message</label>
              <textarea className="form-control" rows={2} value={f.message} onChange={(e) => this.setVoucher('message', e.target.value)} />
            </div>
            <div className="col-12">
              <div className="form-check">
                <input id="vf-send" type="checkbox" className="form-check-input" checked={f.send_email} disabled={!f.recipient_email}
                  onChange={(e) => this.setVoucher('send_email', e.target.checked)} />
                <label htmlFor="vf-send" className="form-check-label">Email the voucher code to the recipient</label>
              </div>
            </div>
          </div>
          <div className="d-flex gap-2 mt-4">
            <button type="submit" className="btn btn-accent" disabled={saving}>{saving ? 'Issuing…' : 'Issue voucher'}</button>
            <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ voucherForm: null })}>Cancel</button>
          </div>
        </div>
      </form>
    );
  }

  private renderLookup(): React.ReactNode {
    const { lookupCode, lookup, lookupError } = this.state;
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-body p-3">
          <form className="d-flex flex-wrap gap-2 align-items-center" onSubmit={this.doLookup}>
            <label htmlFor="lookup" className="fw-semibold me-1"><i className="bi bi-search me-1" aria-hidden="true" />Balance check</label>
            <input id="lookup" className="form-control text-uppercase font-monospace" style={{ maxWidth: 220 }} placeholder="GV-XXXX-XXXX"
              value={lookupCode} onChange={(e) => this.setState({ lookupCode: e.target.value })} />
            <button type="submit" className="btn btn-primary" disabled={!lookupCode.trim()}>Check</button>
          </form>
          {lookupError && <div className="text-danger small mt-2">{lookupError}</div>}
          {lookup && (
            <div className="mt-3">
              <div className="d-flex flex-wrap gap-3 align-items-center">
                <strong className="font-monospace">{lookup.code}</strong>
                {this.voucherStatus(lookup)}
                <span>Balance <strong>{formatINR(lookup.balance)}</strong> of {formatINR(lookup.initial_value)}</span>
                <span className="text-muted small">Valid until {formatDate(lookup.valid_until)}</span>
                {lookup.recipient_name && <span className="text-muted small">For {lookup.recipient_name}</span>}
              </div>
              {lookup.redemptions.length > 0 && (
                <ul className="small mb-0 mt-2">
                  {lookup.redemptions.map((r) => (
                    <li key={r.id}>
                      <span className="font-monospace">{r.booking_reference}</span> · {formatINR(r.amount)} · {formatDateTime(r.created_at)}
                      {r.reversed_at && <span className="text-success"> · returned to balance</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  private renderVouchers(): React.ReactNode {
    const { vouchers, voucherForm, voucherSearch, voucherPage, issued } = this.state;
    const admin = this.isAdmin;
    return (
      <>
        {this.renderLookup()}
        {issued && (
          <div className="alert alert-success d-flex flex-wrap align-items-center gap-2">
            <i className="bi bi-gift-fill" aria-hidden="true" />
            New voucher <strong className="font-monospace fs-5">{issued.code}</strong> worth {formatINR(issued.initial_value)},
            valid until {formatDate(issued.valid_until)}.
            <button type="button" className="btn-close ms-auto" aria-label="Close" onClick={() => this.setState({ issued: null })} />
          </div>
        )}
        {voucherForm ? this.renderVoucherForm(voucherForm) : (
          <div className="d-flex flex-wrap gap-2 mb-3">
            <input className="form-control" style={{ maxWidth: 280 }} placeholder="Search code, name or email…" value={voucherSearch}
              onChange={(e) => this.setState({ voucherSearch: e.target.value, voucherPage: 1 })} />
            <button className="btn btn-accent ms-auto" onClick={() => this.setState({ voucherForm: emptyVoucher(), notice: '', error: '' })}>
              <i className="bi bi-gift me-1" aria-hidden="true" />Issue voucher
            </button>
          </div>
        )}
        {!vouchers ? <Loader /> : vouchers.results.length === 0 ? <Empty title="No gift vouchers yet" /> : (
          <div className="card border-0 shadow-sm">
            <div className="table-responsive">
              <table className="table table-hover align-middle mb-0">
                <thead className="table-light">
                  <tr><th>Code</th><th className="text-end">Value</th><th className="text-end">Balance</th><th>Recipient</th><th>Valid until</th><th>Uses</th><th>Status</th><th /></tr>
                </thead>
                <tbody>
                  {vouchers.results.map((v) => (
                    <tr key={v.id}>
                      <td>
                        <strong className="font-monospace">{v.code}</strong>
                        <div className="small text-muted">{formatDate(v.created_at)}{v.issued_by_email && ` · ${v.issued_by_email}`}</div>
                      </td>
                      <td className="text-end">{formatINR(v.initial_value)}</td>
                      <td className="text-end fw-semibold">{formatINR(v.balance)}</td>
                      <td className="small">
                        {v.recipient_name || '—'}
                        {v.recipient_email && <div className="text-muted">{v.recipient_email}</div>}
                      </td>
                      <td className="small">{formatDate(v.valid_until)}</td>
                      <td className="small">{v.redemptions.filter((r) => !r.reversed_at).length}</td>
                      <td>{this.voucherStatus(v)}</td>
                      <td className="text-end text-nowrap">
                        {v.recipient_email && (
                          <button className="btn btn-sm btn-outline-primary me-1" title="Email to recipient" onClick={() => this.emailVoucher(v)}
                            disabled={!admin}>
                            <i className="bi bi-envelope" aria-hidden="true" />
                          </button>
                        )}
                        {admin && v.is_active && (
                          <button className="btn btn-sm btn-outline-danger" title="Deactivate" onClick={() => this.deactivateVoucher(v)}>
                            <i className="bi bi-slash-circle" aria-hidden="true" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {vouchers && <Pagination page={voucherPage} count={vouchers.count} onChange={(voucherPage: number) => this.setState({ voucherPage })} />}
      </>
    );
  }

  public render(): React.ReactNode {
    const { tab, error, notice } = this.state;
    return (
      <div>
        <h1 className="h3 mb-3"><i className="bi bi-tag me-2" aria-hidden="true" />Promotions</h1>
        <ul className="nav nav-tabs mb-3">
          {this.isAdmin && (
            <li className="nav-item">
              <button className={`nav-link ${tab === 'promo' ? 'active' : ''}`} onClick={() => this.setState({ tab: 'promo', error: '', notice: '' })}>
                <i className="bi bi-percent me-1" aria-hidden="true" />Promo codes
              </button>
            </li>
          )}
          <li className="nav-item">
            <button className={`nav-link ${tab === 'voucher' ? 'active' : ''}`} onClick={() => this.setState({ tab: 'voucher', error: '', notice: '' })}>
              <i className="bi bi-gift me-1" aria-hidden="true" />Gift vouchers
            </button>
          </li>
        </ul>
        {error && <div className="alert alert-danger">{error}</div>}
        {notice && <div className="alert alert-success">{notice}</div>}
        {tab === 'promo' ? this.renderPromos() : this.renderVouchers()}
      </div>
    );
  }
}

export default withAuth(PromotionsPage);
