import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { ExportJob } from '../../api/exports';
import type { Booking, BookingStatus, Paginated } from '../../api/types';
import { Empty, Loader, Pagination, StatusBadge } from '../../components/Common';
import { formatDate, formatDateTime, formatINR, formatTime } from '../../utils/format';
import { ExportMenu, ExportToast } from './Exports';

const STATUSES: BookingStatus[] = ['pending', 'confirmed', 'checked_in', 'cancelled', 'expired'];

interface AdminBookingsProps {}

interface AdminBookingsState {
  data: Paginated<Booking> | null;
  page: number;
  search: string;
  status: string;
  visitDate: string;
  channel: string;
  isGroup: string;
  selected: Booking | null;
  error: string;
  reload: number;
  started: ExportJob | null;
}

class AdminBookingsPage extends React.Component<AdminBookingsProps, AdminBookingsState> {
  public state: AdminBookingsState = {
    data: null,
    page: 1,
    search: '',
    status: '',
    visitDate: '',
    channel: '',
    isGroup: '',
    selected: null,
    error: '',
    reload: 0,
    started: null,
  };

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_prevProps: AdminBookingsProps, prevState: AdminBookingsState): void {
    const s = this.state;
    if (
      s.page !== prevState.page ||
      s.search !== prevState.search ||
      s.status !== prevState.status ||
      s.visitDate !== prevState.visitDate ||
      s.channel !== prevState.channel ||
      s.isGroup !== prevState.isGroup ||
      s.reload !== prevState.reload
    ) {
      this.scheduleLoad();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      const { page, search, status, visitDate, channel, isGroup } = this.state;
      this.setState({ data: null });
      api
        .get<Paginated<Booking>>('/bookings/', {
          params: {
            page, search: search || undefined, status: status || undefined,
            visit_date: visitDate || undefined, channel: channel || undefined,
            is_group: isGroup || undefined,
          },
        })
        .then((r) => {
          if (this.mounted) this.setState({ data: r.data });
        })
        .catch((err) => {
          // e.g. a staff user not yet assigned to any place gets 403 with an explanation
          if (this.mounted) this.setState({ error: errorMessage(err), data: { count: 0, next: null, previous: null, results: [] } });
        });
    }, 250);
  }

  private cancel = async (b: Booking): Promise<void> => {
    if (!confirm(`Cancel booking ${b.reference}?`)) return;
    try {
      const { data: updated } = await api.post<Booking>(`/bookings/${b.reference}/cancel/`);
      this.setState((s) => ({ selected: updated, reload: s.reload + 1 }));
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private setPage = (page: number): void => {
    this.setState({ page });
  };

  public render(): React.ReactNode {
    const { data, page, search, status, visitDate, channel, isGroup, selected, error, started } = this.state;

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Bookings</h1>
          <ExportMenu
            filters={{ search, status, channel, is_group: isGroup, visit_date: visitDate }}
            onStarted={(job) => this.setState({ started: job, error: '' })}
            onError={(message) => this.setState({ error: message })}
          />
        </div>
        <ExportToast job={started} onClose={() => this.setState({ started: null })} />
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-12 col-xl-3">
                <input className="form-control" placeholder="Reference, name, email, phone, museum…" value={search} onChange={(e) => this.setState({ search: e.target.value, page: 1 })} aria-label="Search bookings" />
              </div>
              <div className="col-sm-6 col-md-4 col-xl-2">
                <select className="form-select" value={status} onChange={(e) => this.setState({ status: e.target.value, page: 1 })} aria-label="Status">
                  <option value="">All statuses</option>
                  {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                </select>
              </div>
              <div className="col-sm-6 col-md-4 col-xl-2">
                <select className="form-select" value={channel} onChange={(e) => this.setState({ channel: e.target.value, page: 1 })} aria-label="Channel">
                  <option value="">Online + counter</option>
                  <option value="online">Online only</option>
                  <option value="counter">Counter only</option>
                </select>
              </div>
              <div className="col-sm-6 col-md-4 col-xl-2">
                <select className="form-select" value={isGroup} onChange={(e) => this.setState({ isGroup: e.target.value, page: 1 })} aria-label="Booking type">
                  <option value="">Groups + individuals</option>
                  <option value="true">Groups only</option>
                  <option value="false">Individuals only</option>
                </select>
              </div>
              <div className="col-sm-6 col-md-4 col-xl-2">
                <input type="date" className="form-control" value={visitDate} onChange={(e) => this.setState({ visitDate: e.target.value, page: 1 })} aria-label="Visit date" />
              </div>
              <div className="col-sm-6 col-md-4 col-xl-1 d-grid">
                <button className="btn btn-light" onClick={() => this.setState({ search: '', status: '', visitDate: '', channel: '', isGroup: '', page: 1 })} title="Reset filters" aria-label="Reset filters">
                  <i className="bi bi-arrow-counterclockwise" aria-hidden="true" /><span className="ms-1 d-xl-none">Reset</span>
                </button>
              </div>
            </div>
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}

        {data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title="No bookings found" />
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0">
                  <thead className="table-light">
                    <tr><th>Reference</th><th>Visitor</th><th>Museum</th><th>Visit</th><th className="text-end">Visitors</th><th className="text-end">Amount</th><th>Status</th><th>Booked</th><th /></tr>
                  </thead>
                  <tbody>
                    {data.results.map((b) => (
                      <tr key={b.reference}>
                        <td className="ref">{b.reference}</td>
                        <td>
                          {b.is_group && <span className="badge bg-accent me-1">Group</span>}
                          {b.visitor_name}
                          {b.is_group && b.organisation_name && <div className="small fw-semibold">{b.organisation_name}</div>}
                          <div className="text-muted small">{b.visitor_phone}</div>
                        </td>
                        <td>{b.museum_name}<div className="text-muted small">{b.city_name}</div></td>
                        <td>{formatDate(b.visit_date)}<div className="text-muted small">{formatTime(b.slot_start)}</div></td>
                        <td className="text-end">{b.total_visitors}</td>
                        <td className="text-end">{formatINR(b.total_amount)}</td>
                        <td><StatusBadge status={b.status} /></td>
                        <td className="text-muted small">
                          {formatDateTime(b.created_at)}
                          <div>{b.channel === 'counter' ? 'Counter' : 'Online'}</div>
                        </td>
                        <td className="text-end"><button className="btn btn-sm btn-light" onClick={() => this.setState({ selected: b })}>View</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mt-3">
              <Pagination page={page} count={data.count} onChange={this.setPage} />
            </div>
          </>
        )}

        {selected && (
          <div className="card border-0 shadow-sm mt-4">
            <div className="card-header bg-white d-flex justify-content-between align-items-center gap-2 py-3">
              <h2 className="h4 mb-0"><span className="ref">{selected.reference}</span> · {selected.museum_name}</h2>
              <button className="btn btn-sm btn-light" onClick={() => this.setState({ selected: null })}>
                <i className="bi bi-x-lg me-1" aria-hidden="true" /> Close
              </button>
            </div>
            <div className="card-body">
              <div className="row g-2 mb-3">
                <div className="col-sm-6 col-lg-4"><div className="fact"><span className="label">Status</span><strong><StatusBadge status={selected.status} /></strong></div></div>
                <div className="col-sm-6 col-lg-4"><div className="fact"><span className="label">Visit</span><strong>{formatDate(selected.visit_date)}, {formatTime(selected.slot_start)}</strong></div></div>
                <div className="col-sm-6 col-lg-4"><div className="fact"><span className="label">Lead visitor</span><strong>{selected.visitor_name}</strong></div></div>
                <div className="col-sm-6 col-lg-4"><div className="fact"><span className="label">Contact</span><strong>{selected.visitor_phone}</strong><div className="small">{selected.visitor_email}</div></div></div>
                <div className="col-sm-6 col-lg-4">
                  <div className="fact">
                    <span className="label">{selected.channel === 'counter' ? 'Sold at counter by' : 'Booked online by'}</span>
                    <strong className="small">{selected.channel === 'counter' ? selected.sold_by_email : selected.user_email}</strong>
                  </div>
                </div>
                <div className="col-sm-6 col-lg-4"><div className="fact"><span className="label">Payment</span><strong>{selected.payment_method || '—'}</strong><div className="small">{selected.payment_id}</div></div></div>
                {selected.is_group && (
                  <>
                    <div className="col-sm-6 col-lg-4">
                      <div className="fact">
                        <span className="label">Group</span>
                        <strong><span className="badge bg-accent me-1">Group</span>{selected.group_type_label || '—'}</strong>
                        {selected.organisation_name && <div className="small">{selected.organisation_name}</div>}
                      </div>
                    </div>
                    <div className="col-sm-6 col-lg-4">
                      <div className="fact">
                        <span className="label">Escorts</span>
                        <strong>{selected.escort_count}</strong>
                        <div className="small">Free (teachers), included in {selected.total_visitors} visitors</div>
                      </div>
                    </div>
                    <div className="col-sm-6 col-lg-4">
                      <div className="fact">
                        <span className="label">Entered</span>
                        <strong>{selected.visitors_arrived} of {selected.total_visitors}</strong>
                        <div className="small">{selected.remaining_to_enter > 0 ? `${selected.remaining_to_enter} still to come` : 'Everyone has entered'}</div>
                      </div>
                    </div>
                  </>
                )}
              </div>
              <ul className="list-group list-group-flush mb-3">
                {selected.items.map((i) => (
                  <li key={i.ticket_name} className="list-group-item d-flex justify-content-between px-0">
                    <span>{i.quantity} × {i.ticket_name} @ {formatINR(i.unit_price)}</span><span>{formatINR(i.line_total)}</span>
                  </li>
                ))}
                {selected.is_group && Number(selected.discount_amount) > 0 && (
                  <>
                    <li className="list-group-item d-flex justify-content-between px-0">
                      <span>Subtotal</span><span>{formatINR(selected.subtotal_amount)}</span>
                    </li>
                    <li className="list-group-item d-flex justify-content-between px-0 text-success">
                      <span>Group discount</span><span>− {formatINR(selected.discount_amount)}</span>
                    </li>
                  </>
                )}
                <li className="list-group-item d-flex justify-content-between px-0 fs-5 fw-bold">
                  <span>Total</span><span>{formatINR(selected.total_amount)}</span>
                </li>
              </ul>
              {selected.can_cancel && (
                <button className="btn btn-outline-danger btn-sm" onClick={() => this.cancel(selected)}>
                  <i className="bi bi-x-circle me-1" aria-hidden="true" /> Cancel booking
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }
}

export default AdminBookingsPage;
