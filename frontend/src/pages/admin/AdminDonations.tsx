import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { adminDonationParams, downloadDonationsCsv } from '../../api/donations';
import type { AdminDonation, AdminDonationFilters, AdminDonationPage, DonationStatus } from '../../api/donations';
import { Empty, Loader, Pagination } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { formatDate, formatDateTime, formatINR } from '../../utils/format';

/*
 * Admin: donations with filters (status, place / general fund, date range, 80G), totals for the filtered set,
 * refunds, and the CSV the CA needs for Form 10BD (/api/admin/donations/export/).
 */

const STATUS_BADGE: Record<DonationStatus, string> = {
  pending: 'bg-light text-dark border',
  paid: 'bg-success',
  failed: 'bg-danger',
  refunded: 'bg-secondary',
};

type Where = '' | 'general' | 'place';

interface AdminDonationsState {
  data: AdminDonationPage | null;
  page: number;
  search: string;
  status: string;
  where: Where;
  museum: string;
  dateFrom: string;
  dateTo: string;
  wants80g: '' | 'true' | 'false';
  error: string;
  exporting: boolean;
  reload: number;
}

class AdminDonations extends React.Component<Record<string, never>, AdminDonationsState> {
  public state: AdminDonationsState = {
    data: null,
    page: 1,
    search: '',
    status: '',
    where: '',
    museum: '',
    dateFrom: '',
    dateTo: '',
    wants80g: '',
    error: '',
    exporting: false,
    reload: 0,
  };

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_prevProps: Record<string, never>, prev: AdminDonationsState): void {
    const s = this.state;
    if (
      s.page !== prev.page || s.search !== prev.search || s.status !== prev.status || s.where !== prev.where ||
      s.museum !== prev.museum || s.dateFrom !== prev.dateFrom || s.dateTo !== prev.dateTo ||
      s.wants80g !== prev.wants80g || s.reload !== prev.reload
    ) {
      this.scheduleLoad();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private filters(): AdminDonationFilters {
    const { page, search, status, where, museum, dateFrom, dateTo, wants80g } = this.state;
    return {
      page,
      search: search.trim(),
      status,
      museum: where === 'general' ? 'general' : where === 'place' ? museum : '',
      date_from: dateFrom,
      date_to: dateTo,
      wants_80g: wants80g,
    };
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      const id = ++this.requestId;
      api
        .get<AdminDonationPage>('/admin/donations/', { params: adminDonationParams(this.filters()) })
        .then((r) => this.mounted && id === this.requestId && this.setState({ data: r.data, error: '' }))
        .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
    }, 250);
  }

  /** Filter changes go back to page 1. */
  private filter(patch: Partial<AdminDonationsState>): void {
    this.setState({ ...patch, page: 1 } as AdminDonationsState);
  }

  private exportCsv = async (): Promise<void> => {
    this.setState({ exporting: true, error: '' });
    try {
      await downloadDonationsCsv(this.filters());
    } catch (err) {
      this.setState({ error: errorMessage(err, 'The CSV could not be created. Please try again.') });
    } finally {
      if (this.mounted) this.setState({ exporting: false });
    }
  };

  private refund = async (d: AdminDonation): Promise<void> => {
    if (!confirm(`Refund ${formatINR(d.amount)} to ${d.donor_name}? Receipt ${d.receipt_number} will be marked refunded and must not be claimed under 80G.`)) return;
    try {
      await api.post(`/admin/donations/${d.reference}/refund/`);
      this.setState((s) => ({ reload: s.reload + 1 }));
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private clear = (): void => {
    this.filter({ search: '', status: '', where: '', museum: '', dateFrom: '', dateTo: '', wants80g: '' });
  };

  private renderTotals(): React.ReactNode {
    const totals = this.state.data?.totals;
    if (!totals) return null;
    const tiles = [
      { label: 'Received', value: formatINR(totals.paid_amount), note: `${totals.paid_count} paid donation${totals.paid_count === 1 ? '' : 's'}`, icon: 'bi-cash-coin' },
      { label: 'Claimable under 80G', value: formatINR(totals.paid_80g_amount), note: 'Paid, 80G receipt asked for', icon: 'bi-receipt' },
      { label: 'Refunded', value: formatINR(totals.refunded_amount), note: 'Not to be reported in 10BD', icon: 'bi-arrow-counterclockwise' },
      { label: 'Records', value: String(totals.count), note: 'Matching the filters (all statuses)', icon: 'bi-list-ul' },
    ];
    return (
      <div className="row g-3 mb-3">
        {tiles.map((tile) => (
          <div className="col-sm-6 col-xl-3" key={tile.label}>
            <div className="card border-0 shadow-sm h-100">
              <div className="card-body">
                <div className="text-muted small"><i className={`bi ${tile.icon} me-1`} aria-hidden="true" />{tile.label}</div>
                <div className="fs-4 fw-bold">{tile.value}</div>
                <div className="small text-muted">{tile.note}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  public render(): React.ReactNode {
    const { data, page, search, status, where, museum, dateFrom, dateTo, wants80g, error, exporting } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
          <h1 className="h2 mb-0">Donations</h1>
          <button type="button" className="btn btn-accent" onClick={this.exportCsv} disabled={exporting}>
            <i className="bi bi-download me-1" aria-hidden="true" />
            {exporting ? 'Preparing…' : 'Form 10BD CSV'}
          </button>
        </div>
        <p className="text-muted mb-4">
          Gifts to a place or to the general heritage fund. Receipt numbers run per financial year and are given only when a
          donation is paid. The CSV lists paid donations (unless you filter by another status) with the columns your CA needs
          for Form 10BD.
        </p>

        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2 align-items-end">
              <div className="col-lg-4">
                <label htmlFor="ad-search" className="form-label small text-muted mb-1">Search</label>
                <input id="ad-search" className="form-control" placeholder="Name, email, PAN, receipt…" value={search} onChange={(e) => this.filter({ search: e.target.value })} />
              </div>
              <div className="col-sm-4 col-lg-2">
                <label htmlFor="ad-status" className="form-label small text-muted mb-1">Status</label>
                <select id="ad-status" className="form-select" value={status} onChange={(e) => this.filter({ status: e.target.value })}>
                  <option value="">All</option>
                  <option value="paid">Paid</option>
                  <option value="pending">Pending</option>
                  <option value="failed">Failed</option>
                  <option value="refunded">Refunded</option>
                </select>
              </div>
              <div className="col-sm-4 col-lg-2">
                <label htmlFor="ad-80g" className="form-label small text-muted mb-1">80G receipt</label>
                <select id="ad-80g" className="form-select" value={wants80g} onChange={(e) => this.filter({ wants80g: e.target.value as AdminDonationsState['wants80g'] })}>
                  <option value="">Any</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </div>
              <div className="col-sm-4 col-lg-2">
                <label htmlFor="ad-from" className="form-label small text-muted mb-1">From</label>
                <input id="ad-from" type="date" className="form-control" value={dateFrom} max={dateTo || undefined} onChange={(e) => this.filter({ dateFrom: e.target.value })} />
              </div>
              <div className="col-sm-4 col-lg-2">
                <label htmlFor="ad-to" className="form-label small text-muted mb-1">To</label>
                <input id="ad-to" type="date" className="form-control" value={dateTo} min={dateFrom || undefined} onChange={(e) => this.filter({ dateTo: e.target.value })} />
              </div>
              <div className="col-sm-4 col-lg-3">
                <label htmlFor="ad-where" className="form-label small text-muted mb-1">Where it goes</label>
                <select id="ad-where" className="form-select" value={where} onChange={(e) => this.filter({ where: e.target.value as Where, museum: '' })}>
                  <option value="">Everywhere</option>
                  <option value="general">General heritage fund</option>
                  <option value="place">One place…</option>
                </select>
              </div>
              {where === 'place' && (
                <div className="col-sm-8 col-lg-5">
                  <MuseumPicker filter value={museum} label="Place" clearable onChange={(slug) => this.filter({ museum: slug })} />
                </div>
              )}
              <div className="col-auto ms-auto">
                <button type="button" className="btn btn-link" onClick={this.clear}>Clear filters</button>
              </div>
            </div>
          </div>
        </div>

        {error && <div className="alert alert-danger">{error}</div>}
        {this.renderTotals()}

        {data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title="No donations">Nothing matches these filters yet.</Empty>
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0">
                  <thead className="table-light">
                    <tr>
                      <th scope="col">Receipt / date</th>
                      <th scope="col">Donor</th>
                      <th scope="col">For</th>
                      <th scope="col" className="text-end">Amount</th>
                      <th scope="col">80G</th>
                      <th scope="col">Status</th>
                      <th scope="col"><span className="visually-hidden">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.results.map((d) => (
                      <tr key={d.reference}>
                        <td>
                          <div className="ref small">{d.receipt_number ?? d.reference}</div>
                          <div className="small text-muted">{d.paid_at ? formatDate(d.paid_at) : formatDateTime(d.created_at)}</div>
                        </td>
                        <td>
                          <div className="fw-semibold">{d.donor_name}</div>
                          <div className="small text-muted">{d.donor_email}{d.donor_phone ? ` · ${d.donor_phone}` : ''}</div>
                          {d.donor_pan && <div className="small">PAN <span className="ref">{d.donor_pan}</span></div>}
                        </td>
                        <td className="small">
                          {d.museum_slug ? <Link to={`/museums/${d.museum_slug}`} target="_blank">{d.museum_name}</Link> : 'General heritage fund'}
                        </td>
                        <td className="text-end fw-semibold">{formatINR(d.amount)}</td>
                        <td>
                          {d.wants_80g ? <span className="badge bg-primary">80G</span> : <span className="text-muted small">—</span>}
                        </td>
                        <td>
                          <span className={`badge ${STATUS_BADGE[d.status]}`}>{d.status_label}</span>
                          {d.payment_id && <div className="small text-muted ref">{d.payment_id}</div>}
                        </td>
                        <td className="text-end text-nowrap">
                          {d.status === 'paid' && (
                            <>
                              <Link to={`/donations/${d.reference}`} target="_blank" className="btn btn-outline-primary btn-sm me-1" title="Open receipt">
                                <i className="bi bi-receipt" aria-hidden="true" /><span className="visually-hidden">Open receipt</span>
                              </Link>
                              <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => this.refund(d)} title="Refund">
                                <i className="bi bi-arrow-counterclockwise" aria-hidden="true" /><span className="visually-hidden">Refund</span>
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
            <div className="mt-3">
              <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />
            </div>
          </>
        )}
      </div>
    );
  }
}

export default AdminDonations;
