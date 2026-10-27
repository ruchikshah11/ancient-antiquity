import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { AgentPayment, AgentProfile, AgentStatus, KioskDevice } from '../../api/partners';
import type { Paginated } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { formatDate, formatDateTime, formatINR, isoDate } from '../../utils/format';

/** Admin: tour operator applications/accounts and self-service kiosk devices. */

type Tab = 'agents' | 'kiosks';

const STATUS_BADGE: Record<AgentStatus, string> = {
  pending: 'bg-warning text-dark',
  approved: 'bg-success',
  rejected: 'bg-secondary',
  suspended: 'bg-danger',
};

interface PartnersState {
  tab: Tab;
}

export default class Partners extends React.Component<Record<string, never>, PartnersState> {
  public state: PartnersState = { tab: 'agents' };

  public render(): React.ReactNode {
    const { tab } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
          <h1 className="h2 mb-0">Partners</h1>
        </div>
        <ul className="nav nav-tabs mb-4" role="tablist">
          {(
            [
              ['agents', 'Tour operators', 'bi-briefcase'],
              ['kiosks', 'Kiosks', 'bi-tablet'],
            ] as const
          ).map(([id, label, icon]) => (
            <li className="nav-item" key={id} role="presentation">
              <button type="button" role="tab" aria-selected={tab === id} className={`nav-link ${tab === id ? 'active' : ''}`} onClick={() => this.setState({ tab: id })}>
                <i className={`bi ${icon} me-1`} aria-hidden="true" />
                {label}
              </button>
            </li>
          ))}
        </ul>
        {tab === 'agents' ? <AgentsTab /> : <KiosksTab />}
      </div>
    );
  }
}

// ------------------------------------------------------------------------------------------- tour operators

interface AgentForm {
  commission_percent: string;
  credit_limit: string;
  admin_note: string;
}

interface AgentsState {
  status: '' | AgentStatus;
  search: string;
  page: number;
  data: Paginated<AgentProfile> | null;
  error: string;
  info: string;
  editing: AgentProfile | null;
  approving: boolean;
  form: AgentForm;
  paymentsFor: AgentProfile | null;
  payments: AgentPayment[] | null;
  payment: { amount: string; reference: string; note: string; received_on: string };
  busy: boolean;
  modalError: string;
}

class AgentsTab extends React.Component<Record<string, never>, AgentsState> {
  public state: AgentsState = {
    status: 'pending', search: '', page: 1, data: null, error: '', info: '', editing: null, approving: false,
    form: { commission_percent: '5', credit_limit: '0', admin_note: '' }, paymentsFor: null, payments: null,
    payment: { amount: '', reference: '', note: '', received_on: isoDate(0) }, busy: false, modalError: '',
  };

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

  public componentDidUpdate(_p: Record<string, never>, prev: AgentsState): void {
    if (prev.status !== this.state.status || prev.page !== this.state.page) this.load();
    if (prev.search !== this.state.search) {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => (this.state.page === 1 ? this.load() : this.setState({ page: 1 })), 300);
    }
  }

  private load = (): void => {
    const { status, search, page } = this.state;
    api
      .get<Paginated<AgentProfile>>('/admin/agents/', { params: { status: status || undefined, search: search || undefined, page } })
      .then((r) => this.mounted && this.setState({ data: r.data, error: '' }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  };

  private openEdit = (a: AgentProfile, approving: boolean): void => {
    this.setState({
      editing: a, approving, modalError: '',
      form: { commission_percent: String(Number(a.commission_percent)), credit_limit: String(Number(a.credit_limit)), admin_note: a.admin_note },
    });
  };

  private saveEdit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { editing, approving, form } = this.state;
    if (!editing) return;
    this.setState({ busy: true, modalError: '' });
    try {
      if (approving) {
        await api.post(`/admin/agents/${editing.id}/approve/`, { commission_percent: form.commission_percent, credit_limit: form.credit_limit });
        if (form.admin_note !== editing.admin_note) await api.patch(`/admin/agents/${editing.id}/`, { admin_note: form.admin_note });
      } else {
        await api.patch(`/admin/agents/${editing.id}/`, form);
      }
      this.setState({ editing: null, busy: false, info: approving ? `${editing.company_name} approved.` : 'Saved.' });
      this.load();
    } catch (err) {
      this.setState({ busy: false, modalError: errorMessage(err) });
    }
  };

  private reject = async (a: AgentProfile): Promise<void> => {
    const verb = a.is_approved ? 'Suspend' : 'Reject';
    const reason = window.prompt(`${verb} ${a.company_name}? Optional reason (shown to the applicant):`, '');
    if (reason === null) return;
    try {
      await api.post(`/admin/agents/${a.id}/reject/`, { reason });
      this.setState({ info: `${a.company_name}: ${a.is_approved ? 'suspended' : 'rejected'}.` });
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private openPayments = (a: AgentProfile): void => {
    this.setState({ paymentsFor: a, payments: null, modalError: '', payment: { amount: '', reference: '', note: '', received_on: isoDate(0) } });
    api.get<AgentPayment[]>(`/admin/agents/${a.id}/payments/`).then((r) => this.mounted && this.setState({ payments: r.data }));
  };

  private recordPayment = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { paymentsFor, payment } = this.state;
    if (!paymentsFor) return;
    this.setState({ busy: true, modalError: '' });
    try {
      const { data } = await api.post<{ payment: AgentPayment; agent: AgentProfile }>(`/admin/agents/${paymentsFor.id}/payments/`, payment);
      this.setState((s) => ({
        busy: false, paymentsFor: data.agent, payments: [data.payment, ...(s.payments ?? [])],
        payment: { amount: '', reference: '', note: '', received_on: isoDate(0) },
      }));
      this.load();
    } catch (err) {
      this.setState({ busy: false, modalError: errorMessage(err) });
    }
  };

  private renderEditModal(): React.ReactNode {
    const { editing, approving, form, busy, modalError } = this.state;
    if (!editing) return null;
    const set = (k: keyof AgentForm, v: string) => this.setState((s) => ({ form: { ...s.form, [k]: v } }));
    return (
      <div className="modal show-react" role="dialog" aria-modal="true" aria-labelledby="agent-edit-title">
        <div className="modal-dialog">
          <form className="modal-content" onSubmit={this.saveEdit}>
            <div className="modal-header">
              <h2 className="modal-title h5" id="agent-edit-title">{approving ? 'Approve' : 'Edit'} {editing.company_name}</h2>
              <button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ editing: null })} />
            </div>
            <div className="modal-body">
              {modalError && <div className="alert alert-danger">{modalError}</div>}
              <dl className="row small mb-3">
                <dt className="col-4">Account</dt><dd className="col-8">{editing.email}</dd>
                <dt className="col-4">Phone</dt><dd className="col-8">{editing.contact_phone}</dd>
                <dt className="col-4">GSTIN</dt><dd className="col-8">{editing.gstin || '–'}</dd>
                <dt className="col-4">City</dt><dd className="col-8">{editing.city || '–'}</dd>
                {editing.message && (<><dt className="col-4">Message</dt><dd className="col-8">{editing.message}</dd></>)}
              </dl>
              <div className="row g-3">
                <div className="col-6">
                  <label htmlFor="ae-comm" className="form-label">Commission %</label>
                  <input id="ae-comm" type="number" step="0.01" min={0} max={50} className="form-control" required value={form.commission_percent} onChange={(e) => set('commission_percent', e.target.value)} />
                </div>
                <div className="col-6">
                  <label htmlFor="ae-credit" className="form-label">Credit limit (₹)</label>
                  <input id="ae-credit" type="number" step="1" min={0} className="form-control" required value={form.credit_limit} onChange={(e) => set('credit_limit', e.target.value)} />
                </div>
                <div className="col-12">
                  <label htmlFor="ae-note" className="form-label">Internal note</label>
                  <input id="ae-note" className="form-control" maxLength={255} value={form.admin_note} onChange={(e) => set('admin_note', e.target.value)} />
                </div>
              </div>
              {approving && <p className="small text-muted mt-3 mb-0">Approving changes the account's role to tour operator. They can then book on account up to the credit limit.</p>}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ editing: null })}>Cancel</button>
              <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : approving ? 'Approve' : 'Save'}</button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  private renderPaymentsModal(): React.ReactNode {
    const { paymentsFor: a, payments, payment, busy, modalError } = this.state;
    if (!a) return null;
    const set = (k: keyof AgentsState['payment'], v: string) => this.setState((s) => ({ payment: { ...s.payment, [k]: v } }));
    return (
      <div className="modal show-react" role="dialog" aria-modal="true" aria-labelledby="agent-pay-title">
        <div className="modal-dialog modal-lg">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title h5" id="agent-pay-title">Payments · {a.company_name}</h2>
              <button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ paymentsFor: null })} />
            </div>
            <div className="modal-body">
              <div className="row g-2 mb-3">
                <div className="col-4"><div className="fact"><span className="label">Balance owed</span><strong>{formatINR(a.balance)}</strong></div></div>
                <div className="col-4"><div className="fact"><span className="label">Credit limit</span><strong>{formatINR(a.credit_limit)}</strong></div></div>
                <div className="col-4"><div className="fact"><span className="label">Available</span><strong>{formatINR(a.credit_available)}</strong></div></div>
              </div>
              {modalError && <div className="alert alert-danger">{modalError}</div>}
              <form className="row g-2 align-items-end mb-3" onSubmit={this.recordPayment}>
                <div className="col-md-3">
                  <label htmlFor="ap-amt" className="form-label small">Amount (₹)</label>
                  <input id="ap-amt" type="number" step="0.01" min="0.01" className="form-control" required value={payment.amount} onChange={(e) => set('amount', e.target.value)} />
                </div>
                <div className="col-md-3">
                  <label htmlFor="ap-ref" className="form-label small">UTR / reference</label>
                  <input id="ap-ref" className="form-control" required maxLength={80} value={payment.reference} onChange={(e) => set('reference', e.target.value)} />
                </div>
                <div className="col-md-3">
                  <label htmlFor="ap-date" className="form-label small">Received on</label>
                  <input id="ap-date" type="date" className="form-control" max={isoDate(0)} required value={payment.received_on} onChange={(e) => set('received_on', e.target.value)} />
                </div>
                <div className="col-md-3">
                  <button className="btn btn-accent w-100" disabled={busy}>{busy ? 'Saving…' : 'Record payment'}</button>
                </div>
                <div className="col-12">
                  <input className="form-control form-control-sm" placeholder="Note (optional)" aria-label="Note" maxLength={255} value={payment.note} onChange={(e) => set('note', e.target.value)} />
                </div>
              </form>
              {!payments ? <Loader /> : payments.length === 0 ? <p className="text-muted mb-0">No payments recorded yet.</p> : (
                <table className="table table-sm mb-0">
                  <thead><tr><th>Received</th><th>Reference</th><th>Note</th><th>By</th><th className="text-end">Amount</th></tr></thead>
                  <tbody>
                    {payments.map((p) => (
                      <tr key={p.id}>
                        <td>{formatDate(p.received_on)}</td>
                        <td>{p.reference}</td>
                        <td className="small">{p.note}</td>
                        <td className="small">{p.recorded_by_email}</td>
                        <td className="text-end">{formatINR(p.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { status, search, page, data, error, info } = this.state;
    return (
      <div>
        <div className="d-flex flex-wrap gap-2 mb-3">
          <select className="form-select w-auto" aria-label="Status" value={status} onChange={(e) => this.setState({ status: e.target.value as AgentsState['status'], page: 1 })}>
            <option value="pending">Applications (pending)</option>
            <option value="approved">Approved</option>
            <option value="suspended">Suspended</option>
            <option value="rejected">Rejected</option>
            <option value="">All</option>
          </select>
          <input className="form-control" style={{ maxWidth: 300 }} placeholder="Search company, email, GSTIN…" aria-label="Search" value={search} onChange={(e) => this.setState({ search: e.target.value })} />
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        {info && <div className="alert alert-success alert-dismissible">{info}<button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ info: '' })} /></div>}
        {!data ? <Loader /> : data.results.length === 0 ? <Empty title="No tour operators here" /> : (
          <div className="table-responsive card border-0 shadow-sm">
            <table className="table table-hover align-middle mb-0">
              <thead className="table-light">
                <tr>
                  <th>Company</th><th>Contact</th><th>Status</th><th className="text-end">Commission</th>
                  <th className="text-end">Credit limit</th><th className="text-end">Balance owed</th><th>Applied</th><th />
                </tr>
              </thead>
              <tbody>
                {data.results.map((a) => (
                  <tr key={a.id}>
                    <td><strong>{a.company_name}</strong><div className="small text-muted">{a.gstin || 'No GSTIN'}{a.city ? ` · ${a.city}` : ''}</div></td>
                    <td className="small">{a.email}<div>{a.contact_phone}</div></td>
                    <td><span className={`badge ${STATUS_BADGE[a.status]}`}>{a.status_label}</span>{a.admin_note && <div className="small text-muted text-truncate" style={{ maxWidth: 160 }} title={a.admin_note}>{a.admin_note}</div>}</td>
                    <td className="text-end">{Number(a.commission_percent)}%</td>
                    <td className="text-end">{formatINR(a.credit_limit)}</td>
                    <td className="text-end">{formatINR(a.balance)}</td>
                    <td className="small">{formatDateTime(a.created_at)}</td>
                    <td className="text-end text-nowrap">
                      {a.status !== 'approved' && (
                        <button type="button" className="btn btn-sm btn-success me-1" onClick={() => this.openEdit(a, true)}>Approve</button>
                      )}
                      {a.status === 'approved' && (
                        <>
                          <button type="button" className="btn btn-sm btn-outline-primary me-1" onClick={() => this.openEdit(a, false)} aria-label={`Edit ${a.company_name}`}><i className="bi bi-pencil" aria-hidden="true" /></button>
                          <button type="button" className="btn btn-sm btn-outline-primary me-1" onClick={() => this.openPayments(a)}><i className="bi bi-cash-stack me-1" aria-hidden="true" />Payments</button>
                        </>
                      )}
                      {(a.status === 'pending' || a.status === 'approved') && (
                        <button type="button" className="btn btn-sm btn-outline-danger" onClick={() => this.reject(a)}>{a.status === 'approved' ? 'Suspend' : 'Reject'}</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />}
        {this.renderEditModal()}
        {this.renderPaymentsModal()}
      </div>
    );
  }
}

// ------------------------------------------------------------------------------------------- kiosks

interface KioskForm {
  id: number | null;
  name: string;
  email: string;
  password: string;
  museums: { slug: string; name: string }[];
  is_active: boolean;
}

const emptyKiosk = (): KioskForm => ({ id: null, name: '', email: '', password: '', museums: [], is_active: true });

interface KiosksState {
  data: Paginated<KioskDevice> | null;
  page: number;
  error: string;
  form: KioskForm | null;
  busy: boolean;
  modalError: string;
  pickerKey: number;
}

class KiosksTab extends React.Component<Record<string, never>, KiosksState> {
  public state: KiosksState = { data: null, page: 1, error: '', form: null, busy: false, modalError: '', pickerKey: 0 };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public componentDidUpdate(_p: Record<string, never>, prev: KiosksState): void {
    if (prev.page !== this.state.page) this.load();
  }

  private load = (): void => {
    api
      .get<Paginated<KioskDevice>>('/admin/kiosks/', { params: { page: this.state.page } })
      .then((r) => this.mounted && this.setState({ data: r.data }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  };

  private edit = (k: KioskDevice): void => {
    this.setState({
      modalError: '',
      form: { id: k.id, name: k.name, email: k.email, password: '', is_active: k.is_active, museums: k.museums.map((slug, i) => ({ slug, name: k.museum_names[i] ?? slug })) },
    });
  };

  private addMuseum = (slug: string, name: string): void => {
    if (!slug) return;
    this.setState((s) => (s.form && !s.form.museums.some((m) => m.slug === slug)
      ? { form: { ...s.form, museums: [...s.form.museums, { slug, name }] }, pickerKey: s.pickerKey + 1 }
      : { form: s.form, pickerKey: s.pickerKey + 1 }));
  };

  private save = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { form } = this.state;
    if (!form) return;
    this.setState({ busy: true, modalError: '' });
    const body: Record<string, unknown> = { name: form.name, museums: form.museums.map((m) => m.slug), is_active: form.is_active };
    if (form.password) body.password = form.password;
    try {
      if (form.id) await api.patch(`/admin/kiosks/${form.id}/`, body);
      else await api.post('/admin/kiosks/', { ...body, email: form.email });
      this.setState({ form: null, busy: false });
      this.load();
    } catch (err) {
      this.setState({ busy: false, modalError: errorMessage(err) });
    }
  };

  private renderModal(): React.ReactNode {
    const { form, busy, modalError, pickerKey } = this.state;
    if (!form) return null;
    const set = (patch: Partial<KioskForm>) => this.setState((s) => ({ form: s.form ? { ...s.form, ...patch } : s.form }));
    return (
      <div className="modal show-react" role="dialog" aria-modal="true" aria-labelledby="kiosk-title">
        <div className="modal-dialog">
          <form className="modal-content" onSubmit={this.save}>
            <div className="modal-header">
              <h2 className="modal-title h5" id="kiosk-title">{form.id ? `Edit ${form.name}` : 'New kiosk'}</h2>
              <button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ form: null })} />
            </div>
            <div className="modal-body">
              {modalError && <div className="alert alert-danger">{modalError}</div>}
              <div className="mb-3">
                <label htmlFor="k-name" className="form-label">Device name</label>
                <input id="k-name" className="form-control" required maxLength={100} placeholder="e.g. Red Fort gate 2 kiosk" value={form.name} onChange={(e) => set({ name: e.target.value })} />
              </div>
              <div className="mb-3">
                <label htmlFor="k-email" className="form-label">Sign-in email</label>
                <input id="k-email" type="email" className="form-control" required={!form.id} disabled={!!form.id} value={form.email} onChange={(e) => set({ email: e.target.value })} />
              </div>
              <div className="mb-3">
                <label htmlFor="k-pass" className="form-label">{form.id ? 'New password (leave empty to keep)' : 'Password'}</label>
                <input id="k-pass" type="password" className="form-control" autoComplete="new-password" minLength={8} required={!form.id} value={form.password} onChange={(e) => set({ password: e.target.value })} />
                <div className="form-text">Staff also need this password to change the kiosk's place or sign it out.</div>
              </div>
              <MuseumPicker key={pickerKey} value="" label="Places this kiosk sells for" onChange={this.addMuseum} />
              <div className="d-flex flex-wrap gap-2 mb-3">
                {form.museums.length === 0 && <span className="small text-muted">No places yet.</span>}
                {form.museums.map((m) => (
                  <span key={m.slug} className="badge bg-light text-dark border d-inline-flex align-items-center gap-1 py-2">
                    {m.name}
                    <button type="button" className="btn-close btn-close-sm" style={{ fontSize: '0.6rem' }} aria-label={`Remove ${m.name}`} onClick={() => set({ museums: form.museums.filter((x) => x.slug !== m.slug) })} />
                  </span>
                ))}
              </div>
              {form.id && (
                <div className="form-check form-switch">
                  <input id="k-active" type="checkbox" className="form-check-input" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
                  <label htmlFor="k-active" className="form-check-label">Active (a disabled kiosk cannot sign in or sell)</label>
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ form: null })}>Cancel</button>
              <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { data, page, error } = this.state;
    return (
      <div>
        <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
          <p className="text-muted mb-0">Self-service screens for walk-in visitors. Open <code>/kiosk</code> on the device and sign in with its account.</p>
          <button type="button" className="btn btn-accent" onClick={() => this.setState({ form: emptyKiosk(), modalError: '' })}>
            <i className="bi bi-plus-lg me-1" aria-hidden="true" />New kiosk
          </button>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        {!data ? <Loader /> : data.results.length === 0 ? <Empty title="No kiosks yet" /> : (
          <div className="table-responsive card border-0 shadow-sm">
            <table className="table table-hover align-middle mb-0">
              <thead className="table-light"><tr><th>Device</th><th>Account</th><th>Places</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
              <tbody>
                {data.results.map((k) => (
                  <tr key={k.id}>
                    <td><strong>{k.name}</strong></td>
                    <td className="small">{k.email}</td>
                    <td className="small">{k.museum_names.join(', ') || '–'}</td>
                    <td>{k.is_active ? <span className="badge bg-success">Active</span> : <span className="badge bg-secondary">Disabled</span>}</td>
                    <td className="small">{k.last_login ? formatDateTime(k.last_login) : 'Never'}</td>
                    <td className="text-end"><button type="button" className="btn btn-sm btn-outline-primary" onClick={() => this.edit(k)} aria-label={`Edit ${k.name}`}><i className="bi bi-pencil" aria-hidden="true" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />}
        {this.renderModal()}
      </div>
    );
  }
}
