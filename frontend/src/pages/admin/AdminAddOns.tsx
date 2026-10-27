import * as React from 'react';
import { ADDON_KINDS } from '../../api/addons';
import type { AddOnKind, AddOnPer, AdminAddOn } from '../../api/addons';
import { clearApiCache } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import { Empty, Loader } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatINR } from '../../utils/format';

/** Admin: the add-ons each place sells with its tickets (audio guide, camera permit, wheelchair...). Staff read only. */

interface AddOnForm {
  id: number | null;
  name: string;
  description: string;
  kind: AddOnKind;
  price: string;
  per: AddOnPer;
  max_per_booking: string;
  daily_stock: string;
  is_active: boolean;
  sort: string;
}

const emptyForm = (): AddOnForm => ({
  id: null, name: '', description: '', kind: 'audio_guide', price: '0', per: 'person',
  max_per_booking: '', daily_stock: '', is_active: true, sort: '0',
});

interface AdminAddOnsState {
  museum: string;
  museumName: string;
  addons: AdminAddOn[] | null;
  error: string;
  notice: string;
  form: AddOnForm | null;
  formError: string;
  saving: boolean;
}

class AdminAddOns extends React.Component<WithAuthProps, AdminAddOnsState> {
  public state: AdminAddOnsState = {
    museum: '', museumName: '', addons: null, error: '', notice: '', form: null, formError: '', saving: false,
  };

  private mounted = false;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private get canEdit(): boolean {
    return !!this.props.auth.user?.is_admin_role;
  }

  private choosePlace = (slug: string, name: string): void => {
    this.setState({ museum: slug, museumName: name, form: null, notice: '', error: '' }, this.load);
  };

  private load = (): void => {
    const { museum } = this.state;
    const id = ++this.requestId;
    if (!museum) {
      this.setState({ addons: null });
      return;
    }
    this.setState({ addons: null });
    api
      .get<AdminAddOn[]>('/admin/addons/', { params: { museum } })
      .then(({ data }) => this.mounted && id === this.requestId && this.setState({ addons: data }))
      .catch((err) => this.mounted && id === this.requestId && this.setState({ addons: [], error: errorMessage(err) }));
  };

  private edit = (a: AdminAddOn): void => {
    this.setState({
      form: {
        id: a.id, name: a.name, description: a.description, kind: a.kind, price: a.price, per: a.per,
        max_per_booking: a.max_per_booking === null ? '' : String(a.max_per_booking),
        daily_stock: a.daily_stock === null ? '' : String(a.daily_stock), is_active: a.is_active, sort: String(a.sort),
      },
      formError: '', notice: '',
    });
  };

  private setField = <K extends keyof AddOnForm>(key: K, value: AddOnForm[K]): void => {
    if (this.state.form) this.setState({ form: { ...this.state.form, [key]: value } });
  };

  private save = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { form, museum } = this.state;
    if (!form) return;
    this.setState({ saving: true, formError: '' });
    const payload = {
      museum,
      name: form.name.trim(),
      description: form.description.trim(),
      kind: form.kind,
      price: form.price || '0',
      per: form.per,
      max_per_booking: form.max_per_booking === '' ? null : Number(form.max_per_booking),
      daily_stock: form.daily_stock === '' ? null : Number(form.daily_stock),
      is_active: form.is_active,
      sort: Number(form.sort || 0),
    };
    try {
      if (form.id) await api.patch(`/admin/addons/${form.id}/`, payload);
      else await api.post('/admin/addons/', payload);
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

  private toggle = async (a: AdminAddOn): Promise<void> => {
    try {
      await api.patch(`/admin/addons/${a.id}/`, { is_active: !a.is_active });
      clearApiCache();
      this.load();
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    }
  };

  private remove = async (a: AdminAddOn): Promise<void> => {
    if (!window.confirm(`Delete “${a.name}”? Add-ons that were already sold can only be switched off.`)) return;
    try {
      await api.delete(`/admin/addons/${a.id}/`);
      clearApiCache();
      if (this.mounted) this.setState({ notice: `Deleted “${a.name}”.`, error: '' });
      this.load();
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err), notice: '' });
    }
  };

  private renderForm(form: AddOnForm): React.ReactNode {
    const { formError, saving, museumName } = this.state;
    return (
      <form className="card border-0 shadow-sm mb-4" onSubmit={this.save}>
        <div className="card-header bg-white py-3 d-flex justify-content-between align-items-center">
          <h2 className="h5 mb-0">{form.id ? `Edit ${form.name}` : `New add-on at ${museumName}`}</h2>
          <button type="button" className="btn-close" aria-label="Close form" onClick={() => this.setState({ form: null })} />
        </div>
        <div className="card-body">
          {formError && <div className="alert alert-danger" role="alert">{formError}</div>}
          <div className="row g-3">
            <div className="col-md-4">
              <label htmlFor="ao-kind" className="form-label">Kind</label>
              <select id="ao-kind" className="form-select" value={form.kind} onChange={(e) => this.setField('kind', e.target.value as AddOnKind)}>
                {ADDON_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
            </div>
            <div className="col-md-8">
              <label htmlFor="ao-name" className="form-label">Name</label>
              <input id="ao-name" className="form-control" value={form.name} onChange={(e) => this.setField('name', e.target.value)} required maxLength={80} />
            </div>
            <div className="col-12">
              <label htmlFor="ao-desc" className="form-label">Description</label>
              <input id="ao-desc" className="form-control" value={form.description} onChange={(e) => this.setField('description', e.target.value)} maxLength={255} />
            </div>
            <div className="col-6 col-md-3">
              <label htmlFor="ao-price" className="form-label">Price (₹)</label>
              <input id="ao-price" type="number" min={0} step="0.01" className="form-control" value={form.price} onChange={(e) => this.setField('price', e.target.value)} required />
              <div className="form-text">0 = free</div>
            </div>
            <div className="col-6 col-md-3">
              <label htmlFor="ao-per" className="form-label">Charged</label>
              <select id="ao-per" className="form-select" value={form.per} onChange={(e) => this.setField('per', e.target.value as AddOnPer)}>
                <option value="person">Per person</option>
                <option value="booking">Per booking</option>
              </select>
            </div>
            <div className="col-6 col-md-2">
              <label htmlFor="ao-max" className="form-label">Max per booking</label>
              <input id="ao-max" type="number" min={1} className="form-control" value={form.max_per_booking} placeholder="auto" onChange={(e) => this.setField('max_per_booking', e.target.value)} />
            </div>
            <div className="col-6 col-md-2">
              <label htmlFor="ao-stock" className="form-label">Daily stock</label>
              <input id="ao-stock" type="number" min={0} className="form-control" value={form.daily_stock} placeholder="unlimited" onChange={(e) => this.setField('daily_stock', e.target.value)} />
            </div>
            <div className="col-6 col-md-2">
              <label htmlFor="ao-sort" className="form-label">Order</label>
              <input id="ao-sort" type="number" min={0} className="form-control" value={form.sort} onChange={(e) => this.setField('sort', e.target.value)} />
            </div>
            <div className="col-12">
              <div className="form-check">
                <input id="ao-active" type="checkbox" className="form-check-input" checked={form.is_active} onChange={(e) => this.setField('is_active', e.target.checked)} />
                <label htmlFor="ao-active" className="form-check-label">Offered at checkout</label>
              </div>
              <div className="form-text">
                Max per booking left empty: one per visitor when charged per person, otherwise one per booking.
              </div>
            </div>
          </div>
        </div>
        <div className="card-footer bg-white d-flex gap-2 justify-content-end">
          <button type="button" className="btn btn-light" onClick={() => this.setState({ form: null })}>Cancel</button>
          <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save add-on'}</button>
        </div>
      </form>
    );
  }

  private renderTable(addons: AdminAddOn[]): React.ReactNode {
    const canEdit = this.canEdit;
    return (
      <div className="card border-0 shadow-sm">
        <div className="table-responsive">
          <table className="table table-hover align-middle mb-0">
            <thead className="table-light">
              <tr>
                <th>Add-on</th><th className="text-end">Price</th><th>Charged</th><th className="text-end">Max</th>
                <th className="text-end">Daily stock</th><th className="text-end">Sold</th><th>Status</th>{canEdit && <th />}
              </tr>
            </thead>
            <tbody>
              {addons.map((a) => (
                <tr key={a.id}>
                  <td>
                    <div className="fw-semibold"><i className={`bi bi-${a.icon} me-2 text-accent`} aria-hidden="true" />{a.name}</div>
                    {a.description && <div className="small text-muted">{a.description}</div>}
                  </td>
                  <td className="text-end">{Number(a.price) > 0 ? formatINR(a.price) : 'Free'}</td>
                  <td>{a.per_label}</td>
                  <td className="text-end">{a.max_per_booking ?? <span className="text-muted">auto</span>}</td>
                  <td className="text-end">{a.daily_stock ?? <span className="text-muted">—</span>}</td>
                  <td className="text-end">{a.sold_count}</td>
                  <td><span className={`badge ${a.is_active ? 'bg-success' : 'bg-secondary'}`}>{a.is_active ? 'Offered' : 'Off'}</span></td>
                  {canEdit && (
                    <td className="text-end text-nowrap">
                      <button className="btn btn-sm btn-outline-primary me-1" onClick={() => this.edit(a)} aria-label={`Edit ${a.name}`}>
                        <i className="bi bi-pencil" aria-hidden="true" />
                      </button>
                      <button className="btn btn-sm btn-outline-secondary me-1" onClick={() => this.toggle(a)} aria-label={a.is_active ? `Switch off ${a.name}` : `Offer ${a.name}`} title={a.is_active ? 'Switch off' : 'Offer again'}>
                        <i className={`bi ${a.is_active ? 'bi-toggle-on' : 'bi-toggle-off'}`} aria-hidden="true" />
                      </button>
                      <button className="btn btn-sm btn-outline-danger" onClick={() => this.remove(a)} aria-label={`Delete ${a.name}`}>
                        <i className="bi bi-trash" aria-hidden="true" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { museum, addons, error, notice, form } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Ticket add-ons</h1>
          {this.canEdit && museum && !form && (
            <button className="btn btn-accent" onClick={() => this.setState({ form: emptyForm(), formError: '', notice: '' })}>
              <i className="bi bi-plus-circle me-1" aria-hidden="true" /> New add-on
            </button>
          )}
        </div>
        <div className="mb-4" style={{ maxWidth: 420 }}>
          <MuseumPicker value={museum} onChange={this.choosePlace} label="Place" filter />
        </div>
        {!this.canEdit && <p className="small text-muted">You can see the add-ons of your places. Ask an administrator to change them.</p>}
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        {notice && <div className="alert alert-success" role="status">{notice}</div>}
        {form && this.renderForm(form)}

        {!museum ? (
          <Empty title="Choose a place">
            <p>Add-ons are set per place. Run <code>python manage.py seed_addons</code> for a sample set everywhere.</p>
          </Empty>
        ) : addons === null ? (
          <Loader />
        ) : addons.length === 0 ? (
          <Empty title="No add-ons at this place yet" />
        ) : (
          this.renderTable(addons)
        )}
      </div>
    );
  }
}

export default withAuth(AdminAddOns);
