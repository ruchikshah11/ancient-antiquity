import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import { CHANNEL_LABELS, GenerateResult, PartnerAccount, Settlement, SettlementDetail, SettlementStatus } from '../../api/partners';
import type { Paginated } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDate, formatDateTime, formatINR, isoDate } from '../../utils/format';

/**
 * Partner settlements: what the platform owes each place per period. Admins generate, approve and mark paid;
 * staff see their own places' settlements read-only (the partner view).
 */

const STATUS_BADGE: Record<SettlementStatus, string> = { draft: 'bg-secondary', approved: 'bg-primary', paid: 'bg-success' };

/** First and last day of the previous month, the usual settlement period. */
function lastMonth(): { from: string; to: string } {
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const last = new Date(now.getFullYear(), now.getMonth(), 0);
  const fmt = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { from: fmt(first), to: fmt(last) };
}

type Tab = 'settlements' | 'accounts';

interface State {
  tab: Tab;
  status: '' | SettlementStatus;
  museum: string;
  page: number;
  data: Paginated<Settlement> | null;
  error: string;
  info: string;
  gen: { from: string; to: string; museum: string };
  generating: boolean;
  detail: SettlementDetail | null;
  downloading: boolean;
}

class SettlementsBase extends React.Component<WithAuthProps, State> {
  public state: State = {
    tab: 'settlements', status: '', museum: '', page: 1, data: null, error: '', info: '',
    gen: { ...lastMonth(), museum: '' }, generating: false, detail: null, downloading: false,
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public componentDidUpdate(_p: WithAuthProps, prev: State): void {
    if (prev.status !== this.state.status || prev.museum !== this.state.museum || prev.page !== this.state.page) this.load();
  }

  private isAdmin(): boolean {
    return !!this.props.auth.user?.is_admin_role;
  }

  private params(): Record<string, string | number | undefined> {
    const { status, museum, page } = this.state;
    return { status: status || undefined, museum: museum || undefined, page };
  }

  private load = (): void => {
    api
      .get<Paginated<Settlement>>('/settlements/', { params: this.params() })
      .then((r) => this.mounted && this.setState({ data: r.data, error: '' }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  };

  private generate = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { gen } = this.state;
    this.setState({ generating: true, error: '', info: '' });
    try {
      const { data } = await api.post<GenerateResult>('/admin/settlements/generate/', { from: gen.from, to: gen.to, museum: gen.museum || undefined });
      const skipped = data.skipped.length ? ` Skipped ${data.skipped.length}: ${data.skipped.map((s) => s.museum).join(', ')} (already settled).` : '';
      this.setState({ info: `Created ${data.created.length}, refreshed ${data.updated.length} draft settlement(s).${skipped}`, page: 1, status: '' });
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ generating: false });
    }
  };

  private open = (s: Settlement): void => {
    api.get<SettlementDetail>(`/settlements/${s.id}/`).then((r) => this.mounted && this.setState({ detail: r.data }));
  };

  private act = async (s: Settlement, action: 'approve' | 'mark-paid' | 'delete'): Promise<void> => {
    let body: Record<string, string> | undefined;
    if (action === 'mark-paid') {
      const reference = window.prompt(`Bank transfer / UTR reference for the ${formatINR(s.net_payable)} payout to ${s.museum_name}:`, '');
      if (!reference) return;
      body = { reference };
    } else if (action === 'delete' && !window.confirm(`Delete the draft settlement for ${s.museum_name}?`)) return;
    try {
      if (action === 'delete') await api.delete(`/admin/settlements/${s.id}/`);
      else await api.post(`/admin/settlements/${s.id}/${action}/`, body);
      this.setState({ detail: null, info: `${s.museum_name}: ${action === 'delete' ? 'deleted' : action === 'approve' ? 'approved' : 'marked paid'}.` });
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private downloadCsv = async (): Promise<void> => {
    this.setState({ downloading: true, error: '' });
    try {
      const { page: _page, ...params } = this.params();
      const res = await api.get<Blob>('/settlements/export.csv', { params, responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = `settlements-${isoDate(0)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      this.setState({ error: errorMessage(err, 'The export could not be downloaded.') });
    } finally {
      if (this.mounted) this.setState({ downloading: false });
    }
  };

  private renderDetail(): React.ReactNode {
    const d = this.state.detail;
    if (!d) return null;
    const admin = this.isAdmin();
    const rows: [string, string][] = [
      ['Online', formatINR(d.gross_online)],
      ['Kiosk', formatINR(d.gross_kiosk)],
      ['Tour operators', formatINR(d.gross_agent)],
      ['Counter (collected by the place)', formatINR(d.gross_counter)],
      ['Gross ticket sales', formatINR(d.gross_total)],
      ['Refunds of earlier periods', `− ${formatINR(d.refunds)}`],
      [`Platform fee (${Number(d.platform_fee_percent)}% of gross)`, `− ${formatINR(d.platform_fee)}`],
      ['GST on fee (18%)', `− ${formatINR(d.gst_on_fee)}`],
    ];
    return (
      <div className="modal show-react" role="dialog" aria-modal="true" aria-labelledby="settle-title">
        <div className="modal-dialog modal-lg modal-dialog-scrollable">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title h5" id="settle-title">{d.museum_name} · {formatDate(d.period_start)} – {formatDate(d.period_end)}</h2>
              <button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ detail: null })} />
            </div>
            <div className="modal-body">
              <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
                <span className={`badge ${STATUS_BADGE[d.status]}`}>{d.status_label}</span>
                <span className="small text-muted">{d.booking_count} bookings · {d.visitor_count} visitors</span>
                {d.paid_reference && <span className="small">Paid: <strong>{d.paid_reference}</strong>{d.paid_at && ` on ${formatDateTime(d.paid_at)}`}</span>}
              </div>
              <table className="table table-sm">
                <tbody>
                  {rows.map(([label, value]) => <tr key={label}><td>{label}</td><td className="text-end">{value}</td></tr>)}
                  <tr className="fw-bold"><td>Net payable to the place</td><td className="text-end">{formatINR(d.net_payable)}</td></tr>
                </tbody>
              </table>
              {Number(d.net_payable) < 0 && <div className="alert alert-warning small">Negative: counter cash exceeded the platform's collections, so the place owes the platform this amount.</div>}
              <h3 className="h6">Payout account</h3>
              {d.payout_account ? (
                <p className="small">
                  {d.payout_account.account_holder || '–'} · {d.payout_account.bank_name || '–'} · {d.payout_account.masked_account_number || '–'} · {d.payout_account.ifsc || '–'}
                  {d.payout_account.razorpay_account_id && <> · Razorpay {d.payout_account.razorpay_account_id}</>}
                </p>
              ) : <p className="small text-muted">No payout account on file{admin ? ' (add one under "Payout accounts")' : ''}.</p>}
              <h3 className="h6">Bookings by channel</h3>
              <table className="table table-sm">
                <tbody>
                  {d.by_channel.map((c) => <tr key={c.channel}><td>{CHANNEL_LABELS[c.channel] ?? c.channel}</td><td>{c.bookings}</td><td className="text-end">{formatINR(c.amount)}</td></tr>)}
                </tbody>
              </table>
              <details>
                <summary className="small">Bookings ({d.bookings.length}{d.bookings.length >= 500 ? '+' : ''})</summary>
                <table className="table table-sm small mt-2">
                  <thead><tr><th>Reference</th><th>Paid</th><th>Channel</th><th>Visitors</th><th className="text-end">Amount</th></tr></thead>
                  <tbody>
                    {d.bookings.map((b) => (
                      <tr key={b.reference}><td className="ref">{b.reference}</td><td>{formatDateTime(b.paid_at)}</td><td>{CHANNEL_LABELS[b.channel] ?? b.channel}</td><td>{b.visitors}</td><td className="text-end">{formatINR(b.amount)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </details>
              {d.late_refunds.length > 0 && (
                <details>
                  <summary className="small">Refunds of earlier periods ({d.late_refunds.length})</summary>
                  <ul className="small mt-2">{d.late_refunds.map((r) => <li key={r.reference}>{r.reference} · {formatDateTime(r.cancelled_at)} · {formatINR(r.amount)}</li>)}</ul>
                </details>
              )}
            </div>
            {admin && (
              <div className="modal-footer">
                {d.status === 'draft' && <button type="button" className="btn btn-outline-danger me-auto" onClick={() => this.act(d, 'delete')}>Delete draft</button>}
                {d.status === 'draft' && <button type="button" className="btn btn-primary" onClick={() => this.act(d, 'approve')}>Approve</button>}
                {d.status === 'approved' && <button type="button" className="btn btn-success" onClick={() => this.act(d, 'mark-paid')}>Mark paid</button>}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  private renderSettlements(): React.ReactNode {
    const { status, page, data, gen, generating, downloading } = this.state;
    const admin = this.isAdmin();
    const totals = data?.results.reduce(
      (acc, s) => ({ gross: acc.gross + Number(s.gross_total), net: acc.net + Number(s.net_payable) }),
      { gross: 0, net: 0 },
    );
    return (
      <>
        {admin && (
          <form className="card border-0 shadow-sm mb-4" onSubmit={this.generate}>
            <div className="card-body row g-3 align-items-end">
              <div className="col-sm-6 col-lg-2">
                <label htmlFor="g-from" className="form-label">From</label>
                <input id="g-from" type="date" className="form-control" required value={gen.from} max={isoDate(-1)} onChange={(e) => this.setState({ gen: { ...gen, from: e.target.value } })} />
              </div>
              <div className="col-sm-6 col-lg-2">
                <label htmlFor="g-to" className="form-label">To</label>
                <input id="g-to" type="date" className="form-control" required value={gen.to} max={isoDate(-1)} onChange={(e) => this.setState({ gen: { ...gen, to: e.target.value } })} />
              </div>
              <div className="col-lg-5">
                <MuseumPicker compact value={gen.museum} label="Place (empty = every place with sales)" clearable onChange={(slug) => this.setState({ gen: { ...this.state.gen, museum: slug } })} />
              </div>
              <div className="col-lg-3">
                <button className="btn btn-accent w-100" disabled={generating}>{generating ? 'Generating…' : 'Generate drafts'}</button>
              </div>
              <div className="col-12 small text-muted mt-0">
                Counts bookings paid in the period (cancelled and refunded ones excluded). Platform fee from each place's payout account (default 5%) plus 18% GST. Re-generating refreshes drafts only.
              </div>
            </div>
          </form>
        )}

        <div className="d-flex flex-wrap gap-2 align-items-start mb-3">
          <select className="form-select w-auto" aria-label="Status" value={status} onChange={(e) => this.setState({ status: e.target.value as State['status'], page: 1 })}>
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="paid">Paid</option>
          </select>
          <div style={{ minWidth: 280 }}>
            <MuseumPicker filter value={this.state.museum} label="Filter by place" clearable onChange={(slug) => this.setState({ museum: slug, page: 1 })} />
          </div>
          <button type="button" className="btn btn-outline-primary ms-auto" disabled={downloading} onClick={this.downloadCsv}>
            <i className="bi bi-download me-1" aria-hidden="true" />{downloading ? 'Preparing…' : 'Download CSV'}
          </button>
        </div>

        {!data ? <Loader /> : data.results.length === 0 ? <Empty title="No settlements yet" /> : (
          <div className="table-responsive card border-0 shadow-sm">
            <table className="table table-hover align-middle mb-0">
              <thead className="table-light">
                <tr>
                  <th>Place</th><th>Period</th><th className="text-end">Bookings</th><th className="text-end">Gross</th>
                  <th className="text-end">Fee + GST</th><th className="text-end">Net payable</th><th>Status</th><th />
                </tr>
              </thead>
              <tbody>
                {data.results.map((s) => (
                  <tr key={s.id}>
                    <td>{s.museum_name}<div className="small text-muted">{s.city_name}</div></td>
                    <td className="small">{formatDate(s.period_start)} – {formatDate(s.period_end)}</td>
                    <td className="text-end">{s.booking_count}</td>
                    <td className="text-end">{formatINR(s.gross_total)}</td>
                    <td className="text-end">{formatINR(Number(s.platform_fee) + Number(s.gst_on_fee))}</td>
                    <td className={`text-end fw-semibold ${Number(s.net_payable) < 0 ? 'text-danger' : ''}`}>{formatINR(s.net_payable)}</td>
                    <td><span className={`badge ${STATUS_BADGE[s.status]}`}>{s.status_label}</span></td>
                    <td className="text-end text-nowrap">
                      <button type="button" className="btn btn-sm btn-outline-primary me-1" onClick={() => this.open(s)}>Details</button>
                      {admin && s.status === 'draft' && <button type="button" className="btn btn-sm btn-primary" onClick={() => this.act(s, 'approve')}>Approve</button>}
                      {admin && s.status === 'approved' && <button type="button" className="btn btn-sm btn-success" onClick={() => this.act(s, 'mark-paid')}>Mark paid</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
              {totals && (
                <tfoot className="table-light fw-semibold">
                  <tr><td colSpan={3}>This page</td><td className="text-end">{formatINR(totals.gross)}</td><td /><td className="text-end">{formatINR(totals.net)}</td><td colSpan={2} /></tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
        {data && <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />}
      </>
    );
  }

  public render(): React.ReactNode {
    const { tab, error, info } = this.state;
    const admin = this.isAdmin();
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
          <h1 className="h2 mb-0">Settlements</h1>
          {!admin && <span className="text-muted small">Payout statements for your places (read-only)</span>}
        </div>
        {admin && (
          <ul className="nav nav-tabs mb-4" role="tablist">
            {(
              [
                ['settlements', 'Settlements'],
                ['accounts', 'Payout accounts'],
              ] as const
            ).map(([id, label]) => (
              <li className="nav-item" key={id} role="presentation">
                <button type="button" role="tab" aria-selected={tab === id} className={`nav-link ${tab === id ? 'active' : ''}`} onClick={() => this.setState({ tab: id })}>{label}</button>
              </li>
            ))}
          </ul>
        )}
        {error && <div className="alert alert-danger">{error}</div>}
        {info && <div className="alert alert-success alert-dismissible">{info}<button type="button" className="btn-close" aria-label="Close" onClick={() => this.setState({ info: '' })} /></div>}
        {tab === 'accounts' && admin ? <PayoutAccounts /> : this.renderSettlements()}
        {this.renderDetail()}
      </div>
    );
  }
}

export default withAuth(SettlementsBase);

// ------------------------------------------------------------------------------------------- payout accounts

interface AccountForm {
  id: number | null;
  museum: string;
  museum_name: string;
  account_holder: string;
  bank_name: string;
  account_number: string;
  masked: string;
  ifsc: string;
  razorpay_account_id: string;
  platform_fee_percent: string;
}

const emptyAccount = (): AccountForm => ({
  id: null, museum: '', museum_name: '', account_holder: '', bank_name: '', account_number: '', masked: '', ifsc: '',
  razorpay_account_id: '', platform_fee_percent: '5',
});

interface AccountsState {
  data: Paginated<PartnerAccount> | null;
  page: number;
  form: AccountForm | null;
  busy: boolean;
  error: string;
}

class PayoutAccounts extends React.Component<Record<string, never>, AccountsState> {
  public state: AccountsState = { data: null, page: 1, form: null, busy: false, error: '' };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public componentDidUpdate(_p: Record<string, never>, prev: AccountsState): void {
    if (prev.page !== this.state.page) this.load();
  }

  private load = (): void => {
    api
      .get<Paginated<PartnerAccount>>('/admin/partner-accounts/', { params: { page: this.state.page } })
      .then((r) => this.mounted && this.setState({ data: r.data }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  };

  private save = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { form } = this.state;
    if (!form) return;
    if (!form.museum) {
      this.setState({ error: 'Choose a place.' });
      return;
    }
    const body: Record<string, string> = {
      museum: form.museum, account_holder: form.account_holder, bank_name: form.bank_name, ifsc: form.ifsc,
      razorpay_account_id: form.razorpay_account_id, platform_fee_percent: form.platform_fee_percent,
    };
    if (form.account_number) body.account_number = form.account_number;
    this.setState({ busy: true, error: '' });
    try {
      if (form.id) await api.patch(`/admin/partner-accounts/${form.id}/`, body);
      else await api.post('/admin/partner-accounts/', body);
      this.setState({ form: null, busy: false });
      this.load();
    } catch (err) {
      this.setState({ busy: false, error: errorMessage(err) });
    }
  };

  private renderForm(): React.ReactNode {
    const { form, busy } = this.state;
    if (!form) return null;
    const set = (patch: Partial<AccountForm>) => this.setState((s) => ({ form: s.form ? { ...s.form, ...patch } : s.form }));
    return (
      <form className="card border-0 shadow-sm mb-4" onSubmit={this.save}>
        <div className="card-body row g-3">
          <div className="col-12">
            {form.id ? <div><span className="text-muted small">Place</span><div className="fw-semibold">{form.museum_name}</div></div>
              : <MuseumPicker value={form.museum} label="Place" onChange={(slug, name) => set({ museum: slug, museum_name: name })} />}
          </div>
          <div className="col-md-6"><label htmlFor="pa-holder" className="form-label">Account holder</label><input id="pa-holder" className="form-control" maxLength={150} value={form.account_holder} onChange={(e) => set({ account_holder: e.target.value })} /></div>
          <div className="col-md-6"><label htmlFor="pa-bank" className="form-label">Bank</label><input id="pa-bank" className="form-control" maxLength={100} value={form.bank_name} onChange={(e) => set({ bank_name: e.target.value })} /></div>
          <div className="col-md-6">
            <label htmlFor="pa-num" className="form-label">Account number</label>
            <input id="pa-num" className="form-control" inputMode="numeric" autoComplete="off" maxLength={30} placeholder={form.masked ? `${form.masked} (leave empty to keep)` : ''} value={form.account_number} onChange={(e) => set({ account_number: e.target.value })} />
            <div className="form-text">Stored for payouts; only the last 4 digits are ever shown.</div>
          </div>
          <div className="col-md-6"><label htmlFor="pa-ifsc" className="form-label">IFSC</label><input id="pa-ifsc" className="form-control text-uppercase" maxLength={11} value={form.ifsc} onChange={(e) => set({ ifsc: e.target.value })} /></div>
          <div className="col-md-6"><label htmlFor="pa-rzp" className="form-label">Razorpay linked account (Route)</label><input id="pa-rzp" className="form-control" placeholder="acc_..." maxLength={40} value={form.razorpay_account_id} onChange={(e) => set({ razorpay_account_id: e.target.value })} /></div>
          <div className="col-md-6"><label htmlFor="pa-fee" className="form-label">Platform fee %</label><input id="pa-fee" type="number" step="0.01" min={0} max={50} className="form-control" required value={form.platform_fee_percent} onChange={(e) => set({ platform_fee_percent: e.target.value })} /></div>
          <div className="col-12 d-flex gap-2">
            <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
            <button type="button" className="btn btn-outline-secondary" onClick={() => this.setState({ form: null })}>Cancel</button>
          </div>
        </div>
      </form>
    );
  }

  public render(): React.ReactNode {
    const { data, page, error, form } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center gap-2 mb-3">
          <p className="text-muted mb-0">Where each place's payouts go, and its platform fee. Places without an account use 5%.</p>
          {!form && <button type="button" className="btn btn-accent" onClick={() => this.setState({ form: emptyAccount(), error: '' })}><i className="bi bi-plus-lg me-1" aria-hidden="true" />Add account</button>}
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        {this.renderForm()}
        {!data ? <Loader /> : data.results.length === 0 ? <Empty title="No payout accounts yet" /> : (
          <div className="table-responsive card border-0 shadow-sm">
            <table className="table table-hover align-middle mb-0">
              <thead className="table-light"><tr><th>Place</th><th>Bank</th><th>Account</th><th>IFSC</th><th>Razorpay</th><th className="text-end">Fee</th><th /></tr></thead>
              <tbody>
                {data.results.map((a) => (
                  <tr key={a.id}>
                    <td>{a.museum_name}</td>
                    <td className="small">{a.account_holder}<div className="text-muted">{a.bank_name}</div></td>
                    <td className="ref small">{a.masked_account_number || '–'}</td>
                    <td className="small">{a.ifsc || '–'}</td>
                    <td className="small">{a.razorpay_account_id || '–'}</td>
                    <td className="text-end">{Number(a.platform_fee_percent)}%</td>
                    <td className="text-end">
                      <button type="button" className="btn btn-sm btn-outline-primary" aria-label={`Edit ${a.museum_name}`} onClick={() => this.setState({
                        error: '',
                        form: { id: a.id, museum: a.museum, museum_name: a.museum_name, account_holder: a.account_holder, bank_name: a.bank_name, account_number: '', masked: a.masked_account_number, ifsc: a.ifsc, razorpay_account_id: a.razorpay_account_id, platform_fee_percent: String(Number(a.platform_fee_percent)) },
                      })}><i className="bi bi-pencil" aria-hidden="true" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />}
      </div>
    );
  }
}
