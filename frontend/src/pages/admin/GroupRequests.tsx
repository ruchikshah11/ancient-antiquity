import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import {
  ApproveInput,
  GROUP_REQUEST_STATUSES,
  GroupPlan,
  GroupRequest,
  groupRequestStatus,
  PaymentMode,
  PREFERRED_TIMES,
  PreferredTime,
} from '../../api/groupRequests';
import type { Paginated } from '../../api/types';
import { Empty, Loader, Pagination, StatusBadge } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { formatDate, formatDateTime, formatINR, formatTime, isoDate } from '../../utils/format';

interface AllocationRow {
  key: number;
  slot: string;
  participants: string;
  escorts: string;
}

interface GroupRequestsProps {}

/** Ticket price on the planned date: price = effective price (PriceRule), base_price = usual price. */
interface DatedTicket {
  id: number;
  name: string;
  price: string;
  base_price?: string;
  rule?: string | null;
}

/** GET /group-requests/quote/ for the date in the planner: is the place open, and what do tickets cost. */
interface DateCheck {
  date: string;
  closed: string | null;
  ticket_types: DatedTicket[];
}

interface GroupRequestsState {
  data: Paginated<GroupRequest> | null;
  page: number;
  status: string;
  museum: string;
  date: string;
  search: string;
  reload: number;
  error: string;

  selected: GroupRequest | null;
  planDate: string;
  planTime: PreferredTime;
  plan: GroupPlan | null;
  planning: boolean;
  rows: AllocationRow[];
  ticketType: string;
  discount: string;
  paymentMode: PaymentMode;
  payBy: string;
  staffNotes: string;
  declineReason: string;
  paymentRef: string;
  busy: '' | 'approve' | 'decline' | 'paid' | 'review';
  detailError: string;
  detailMessage: string;
  dateCheck: DateCheck | null;
}

let rowKey = 0;
const PAY_BY_DAYS = 7;

const minDate = (a: string, b: string) => (a < b ? a : b);

class GroupRequestsPage extends React.Component<GroupRequestsProps, GroupRequestsState> {
  public state: GroupRequestsState = {
    data: null,
    page: 1,
    status: 'open',
    museum: '',
    date: '',
    search: '',
    reload: 0,
    error: '',
    selected: null,
    planDate: '',
    planTime: 'any',
    plan: null,
    planning: false,
    rows: [],
    ticketType: '',
    discount: '',
    paymentMode: 'invoice',
    payBy: '',
    staffNotes: '',
    declineReason: '',
    paymentRef: '',
    busy: '',
    detailError: '',
    detailMessage: '',
    dateCheck: null,
  };

  private dateRequest = 0;

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_prevProps: GroupRequestsProps, prev: GroupRequestsState): void {
    const s = this.state;
    if (s.page !== prev.page || s.status !== prev.status || s.museum !== prev.museum || s.date !== prev.date || s.search !== prev.search || s.reload !== prev.reload) {
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
      const { page, status, museum, date, search } = this.state;
      api
        .get<Paginated<GroupRequest>>('/group-requests/', {
          params: { page, status: status || undefined, museum: museum || undefined, date: date || undefined, search: search || undefined },
        })
        .then((r) => {
          if (this.mounted) this.setState({ data: r.data, error: '' });
        })
        .catch((err) => {
          if (this.mounted) this.setState({ error: errorMessage(err), data: { count: 0, next: null, previous: null, results: [] } });
        });
    }, 250);
  }

  // --- detail ----------------------------------------------------------------------------------------

  private select = (r: GroupRequest): void => {
    const open = r.status === 'submitted' || r.status === 'under_review';
    this.setState({
      selected: r,
      planDate: r.approved_date ?? r.preferred_date,
      planTime: r.preferred_time,
      plan: null,
      rows: [],
      ticketType: '',
      discount: '',
      paymentMode: 'invoice',
      payBy: minDate(isoDate(PAY_BY_DAYS), r.preferred_date),
      staffNotes: r.staff_notes,
      declineReason: '',
      paymentRef: '',
      detailError: '',
      detailMessage: '',
      dateCheck: null,
    });
    if (open) {
      this.checkDate(r, r.approved_date ?? r.preferred_date);
      this.suggestPlan(r, r.preferred_date, r.preferred_time);
    }
  };

  /** Closed-day warning and the date's ticket prices, as soon as staff pick a date (before planning). */
  private checkDate = (r: GroupRequest, date: string): void => {
    const id = ++this.dateRequest;
    if (!date) {
      this.setState({ dateCheck: null });
      return;
    }
    api
      .get<DateCheck>('/group-requests/quote/', {
        params: { museum: r.museum_slug, date, participants: r.participants, group_type: r.group_type },
      })
      .then((res) => this.mounted && id === this.dateRequest && this.setState({ dateCheck: res.data }))
      .catch(() => this.mounted && id === this.dateRequest && this.setState({ dateCheck: null }));
  };

  private setPlanDate = (r: GroupRequest, date: string, plan = false): void => {
    this.setState({ planDate: date }, () => plan && this.suggestPlan());
    this.checkDate(r, date);
  };

  private replace(updated: GroupRequest, message = ''): void {
    this.setState((s) => ({
      selected: updated,
      detailMessage: message,
      detailError: '',
      busy: '',
      data: s.data && { ...s.data, results: s.data.results.map((x) => (x.id === updated.id ? updated : x)) },
    }));
  }

  private suggestPlan = async (r?: GroupRequest, date?: string, time?: PreferredTime): Promise<void> => {
    const req = r ?? this.state.selected;
    if (!req) return;
    const planDate = date ?? this.state.planDate;
    const planTime = time ?? this.state.planTime;
    this.setState({ planning: true, detailError: '' });
    try {
      const { data } = await api.get<GroupPlan>(`/group-requests/${req.id}/plan/`, { params: { date: planDate, time: planTime } });
      if (!this.mounted || this.state.selected?.id !== req.id) return;
      this.setState((s) => ({
        planning: false,
        plan: data,
        planDate: data.date,
        rows: data.allocations.map((a) => ({ key: ++rowKey, slot: String(a.slot_id), participants: String(a.participants), escorts: String(a.escorts) })),
        ticketType: s.ticketType || String(data.default_ticket_type?.id ?? ''),
        discount: s.discount || String(data.default_discount_percent),
        payBy: minDate(isoDate(PAY_BY_DAYS), data.date),
        // the plan call moves a submitted request to "under review"
        selected: s.selected && s.selected.status === 'submitted' ? { ...s.selected, status: 'under_review', status_label: 'Under review' } : s.selected,
      }));
      if (req.status === 'submitted') this.setState((s) => ({ reload: s.reload + 1 }));
    } catch (err) {
      if (this.mounted) this.setState({ planning: false, plan: null, detailError: errorMessage(err) });
    }
  };

  private updateRow = (key: number, field: keyof Omit<AllocationRow, 'key'>, value: string): void => {
    this.setState((s) => ({ rows: s.rows.map((r) => (r.key === key ? { ...r, [field]: value } : r)) }));
  };

  private addRow = (): void => {
    const { plan, rows } = this.state;
    const used = new Set(rows.map((r) => r.slot));
    const next = plan?.slots.find((s) => !used.has(String(s.slot_id)));
    this.setState({ rows: [...rows, { key: ++rowKey, slot: next ? String(next.slot_id) : '', participants: '0', escorts: '0' }] });
  };

  private removeRow = (key: number): void => this.setState((s) => ({ rows: s.rows.filter((r) => r.key !== key) }));

  private approve = async (): Promise<void> => {
    const { selected, rows, planDate, ticketType, discount, paymentMode, payBy, staffNotes } = this.state;
    if (!selected) return;
    const allocations = rows
      .filter((r) => r.slot && (Number(r.participants) > 0 || Number(r.escorts) > 0))
      .map((r) => ({ slot: Number(r.slot), participants: Number(r.participants) || 0, escorts: Number(r.escorts) || 0 }));
    if (!allocations.length) {
      this.setState({ detailError: 'Allocate the group to at least one slot.' });
      return;
    }
    const body: ApproveInput = {
      date: planDate,
      allocations,
      ticket_type: ticketType ? Number(ticketType) : undefined,
      discount_percent: Number(discount) || 0,
      payment_mode: paymentMode,
      pay_by: payBy || undefined,
      staff_notes: staffNotes,
    };
    this.setState({ busy: 'approve', detailError: '', detailMessage: '' });
    try {
      const { data } = await api.post<GroupRequest>(`/group-requests/${selected.id}/approve/`, body);
      if (this.mounted) this.replace(data, `Approved: ${data.bookings.length} booking(s) created, total ${formatINR(data.quoted_total)}.`);
    } catch (err) {
      if (this.mounted) this.setState({ busy: '', detailError: errorMessage(err) });
    }
  };

  private decline = async (): Promise<void> => {
    const { selected, declineReason } = this.state;
    if (!selected) return;
    if (!declineReason.trim()) {
      this.setState({ detailError: 'Give the visitor a reason for declining.' });
      return;
    }
    if (!window.confirm(`Decline ${selected.reference}? Any unpaid bookings will be released.`)) return;
    this.setState({ busy: 'decline', detailError: '', detailMessage: '' });
    try {
      const { data } = await api.post<GroupRequest>(`/group-requests/${selected.id}/decline/`, { reason: declineReason.trim() });
      if (this.mounted) this.replace(data, 'Request declined.');
    } catch (err) {
      if (this.mounted) this.setState({ busy: '', detailError: errorMessage(err) });
    }
  };

  private markPaid = async (): Promise<void> => {
    const { selected, paymentRef } = this.state;
    if (!selected) return;
    if (!window.confirm(`Mark all unpaid bookings of ${selected.reference} as paid by bank transfer?`)) return;
    this.setState({ busy: 'paid', detailError: '', detailMessage: '' });
    try {
      const { data } = await api.post<GroupRequest>(`/group-requests/${selected.id}/mark-paid/`, { payment_id: paymentRef.trim() });
      if (this.mounted) this.replace(data, 'Payment recorded; the bookings are confirmed and tickets sent.');
    } catch (err) {
      if (this.mounted) this.setState({ busy: '', detailError: errorMessage(err) });
    }
  };

  private markReview = async (): Promise<void> => {
    const { selected } = this.state;
    if (!selected) return;
    this.setState({ busy: 'review' });
    try {
      const { data } = await api.post<GroupRequest>(`/group-requests/${selected.id}/review/`);
      if (this.mounted) this.replace(data);
    } catch (err) {
      if (this.mounted) this.setState({ busy: '', detailError: errorMessage(err) });
    }
  };

  // --- render ----------------------------------------------------------------------------------------

  private renderPlanner(r: GroupRequest): React.ReactNode {
    const { plan, planning, planDate, planTime, rows, ticketType, discount, paymentMode, payBy, staffNotes, busy, dateCheck } = this.state;
    const ticket = plan?.ticket_types.find((t) => String(t.id) === ticketType) as DatedTicket | undefined;
    const closed = dateCheck && dateCheck.date === planDate ? dateCheck.closed : null;
    const datedPrices = dateCheck && dateCheck.date === planDate ? dateCheck.ticket_types.filter((t) => t.rule) : [];
    const ticketLabel = (t: DatedTicket) =>
      t.rule && t.base_price !== undefined && t.base_price !== t.price
        ? `${t.name} (${formatINR(t.price)}, ${t.rule}; usual ${formatINR(t.base_price)})`
        : `${t.name} (${formatINR(t.price)})`;
    const participants = rows.reduce((n, x) => n + (Number(x.participants) || 0), 0);
    const escorts = rows.reduce((n, x) => n + (Number(x.escorts) || 0), 0);
    const subtotal = ticket ? Number(ticket.price) * participants : 0;
    const total = subtotal - Math.round((subtotal * (Number(discount) || 0)) / 100);
    const slotInfo = (id: string) => plan?.slots.find((s) => String(s.slot_id) === id);
    const slotClosed = (id: string): string => (slotInfo(id) as { closed_reason?: string } | undefined)?.closed_reason ?? '';
    return (
      <div className="border rounded p-3 mb-3">
        <h3 className="h5 mb-3"><i className="bi bi-diagram-3 me-2" aria-hidden="true" />Plan and approve</h3>
        <div className="row g-2 align-items-end mb-3">
          <div className="col-sm-4">
            <label htmlFor="gr-plan-date" className="form-label small mb-1">Visit date</label>
            <input id="gr-plan-date" type="date" className={`form-control ${closed ? 'is-invalid' : ''}`} min={isoDate(0)} value={planDate} onChange={(e) => this.setPlanDate(r, e.target.value)} aria-describedby="gr-plan-date-status" />
          </div>
          <div className="col-sm-4">
            <label htmlFor="gr-plan-time" className="form-label small mb-1">Time of day</label>
            <select id="gr-plan-time" className="form-select" value={planTime} onChange={(e) => this.setState({ planTime: e.target.value as PreferredTime })}>
              {PREFERRED_TIMES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div className="col-sm-4 d-grid">
            <button type="button" className="btn btn-outline-primary" disabled={planning || !planDate} onClick={() => this.suggestPlan()}>
              <i className="bi bi-lightbulb me-1" aria-hidden="true" />{planning ? 'Planning…' : 'Suggest plan'}
            </button>
          </div>
        </div>
        <div id="gr-plan-date-status" aria-live="polite">
          {closed && (
            <div className="alert alert-danger small py-2">
              <i className="bi bi-calendar-x me-1" aria-hidden="true" />
              <strong>Closed:</strong> {closed} Requests can't be approved for this date.
            </div>
          )}
          {!closed && datedPrices.length > 0 && (
            <div className="alert alert-info small py-2">
              <i className="bi bi-tag me-1" aria-hidden="true" />
              Date-based prices on {formatDate(planDate)}:{' '}
              {datedPrices.map((t) => `${t.name} ${formatINR(t.price)} (${t.rule}; usual ${formatINR(t.base_price)})`).join(' · ')}
            </div>
          )}
        </div>
        {r.alternative_date && (
          <p className="small text-muted">
            Visitor's alternative date: <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => this.setPlanDate(r, r.alternative_date!, true)}>{formatDate(r.alternative_date)}</button>
          </p>
        )}

        {plan && (
          <>
            <div className={`alert ${plan.fits ? 'alert-success' : 'alert-warning'} small py-2`}>
              {plan.fits
                ? `Fits: ${plan.people} people over ${plan.allocations.length} consecutive slot(s), keeping ${plan.reserve_percent}% of each slot for individual visitors.`
                : `Does not fit on this day: only ${plan.allocated} of ${plan.people} places available in one consecutive run (keeping ${plan.reserve_percent}% for individuals). Try another date, or adjust the allocation manually.`}
              {plan.note && <div className="mt-1">{plan.note}</div>}
            </div>
            <div className="table-responsive">
              <table className="table table-sm align-middle">
                <thead className="table-light">
                  <tr><th>Slot</th><th>Participants</th><th>Escorts</th><th className="text-end">Free / plan room</th><th /></tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const info = slotInfo(row.slot);
                    const people = (Number(row.participants) || 0) + (Number(row.escorts) || 0);
                    return (
                      <tr key={row.key}>
                        <td style={{ minWidth: 150 }}>
                          <select className={`form-select form-select-sm ${slotClosed(row.slot) ? 'is-invalid' : ''}`} value={row.slot} onChange={(e) => this.updateRow(row.key, 'slot', e.target.value)} aria-label="Slot">
                            <option value="">Choose…</option>
                            {plan.slots.map((s) => (
                              <option key={s.slot_id} value={s.slot_id}>
                                {formatTime(s.start)} – {formatTime(s.end)}{slotClosed(String(s.slot_id)) ? ' (closed)' : ''}
                              </option>
                            ))}
                          </select>
                          {slotClosed(row.slot) && <div className="invalid-feedback">Closed: {slotClosed(row.slot)}</div>}
                        </td>
                        <td style={{ width: 110 }}>
                          <input type="number" min={0} className="form-control form-control-sm" value={row.participants} onChange={(e) => this.updateRow(row.key, 'participants', e.target.value)} aria-label="Participants" />
                        </td>
                        <td style={{ width: 90 }}>
                          <input type="number" min={0} className="form-control form-control-sm" value={row.escorts} onChange={(e) => this.updateRow(row.key, 'escorts', e.target.value)} aria-label="Escorts" />
                        </td>
                        <td className={`text-end small ${info && people > info.free ? 'text-danger fw-bold' : info && people > info.usable ? 'text-accent' : 'text-muted'}`}>
                          {info ? `${info.free} / ${info.usable}` : '–'}
                        </td>
                        <td className="text-end">
                          <button type="button" className="btn btn-sm btn-light" onClick={() => this.removeRow(row.key)} aria-label="Remove slot"><i className="bi bi-trash" aria-hidden="true" /></button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td>
                      <button type="button" className="btn btn-sm btn-light" onClick={this.addRow}><i className="bi bi-plus-lg me-1" aria-hidden="true" />Add slot</button>
                    </td>
                    <td className={`small fw-bold ${participants !== r.participants ? 'text-accent' : ''}`}>{participants} / {r.participants}</td>
                    <td className={`small fw-bold ${escorts !== r.escorts ? 'text-accent' : ''}`}>{escorts} / {r.escorts}</td>
                    <td colSpan={2} className="small text-muted text-end">free / room for group</td>
                  </tr>
                </tfoot>
              </table>
            </div>

            <div className="row g-2">
              <div className="col-sm-6 col-lg-4">
                <label htmlFor="gr-ticket" className="form-label small mb-1">Ticket for participants</label>
                <select id="gr-ticket" className="form-select" value={ticketType} onChange={(e) => this.setState({ ticketType: e.target.value })}>
                  {plan.ticket_types.map((t) => <option key={t.id} value={t.id}>{ticketLabel(t)}</option>)}
                </select>
              </div>
              <div className="col-sm-6 col-lg-2">
                <label htmlFor="gr-discount" className="form-label small mb-1">Discount %</label>
                <input id="gr-discount" type="number" min={0} max={100} className="form-control" value={discount} onChange={(e) => this.setState({ discount: e.target.value })} />
              </div>
              <div className="col-sm-6 col-lg-3">
                <label htmlFor="gr-mode" className="form-label small mb-1">Payment</label>
                <select id="gr-mode" className="form-select" value={paymentMode} onChange={(e) => this.setState({ paymentMode: e.target.value as PaymentMode })}>
                  <option value="invoice">Invoice / bank transfer</option>
                  <option value="online">Online by visitor</option>
                </select>
              </div>
              <div className="col-sm-6 col-lg-3">
                <label htmlFor="gr-payby" className="form-label small mb-1">Pay by</label>
                <input id="gr-payby" type="date" className="form-control" min={isoDate(0)} max={planDate} value={payBy} onChange={(e) => this.setState({ payBy: e.target.value })} />
              </div>
              <div className="col-12">
                <label htmlFor="gr-notes" className="form-label small mb-1">Staff notes <span className="text-muted">(visible to the visitor)</span></label>
                <textarea id="gr-notes" className="form-control" rows={2} value={staffNotes} onChange={(e) => this.setState({ staffNotes: e.target.value })} />
              </div>
            </div>
            <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mt-3">
              <div>
                <span className="text-muted small">Quote for {formatDate(plan.date)}: </span>
                <strong className="fs-5">{formatINR(total)}</strong>
                {subtotal !== total && <span className="text-muted small ms-2"><s>{formatINR(subtotal)}</s></span>}
                {ticket?.rule && <div className="small text-accent"><i className="bi bi-tag me-1" aria-hidden="true" />{ticket.name} at the {ticket.rule} price {formatINR(ticket.price)} (usual {formatINR(ticket.base_price)})</div>}
                <div className="small text-muted">{participants + escorts} people, seats held until the pay-by date (never after the first slot starts).</div>
              </div>
              <button type="button" className="btn btn-success" disabled={busy !== '' || !rows.length || !!closed || plan.date !== planDate} title={plan.date !== planDate ? 'Suggest a plan for the new date first' : undefined} onClick={this.approve}>
                <i className="bi bi-check-circle me-1" aria-hidden="true" />{busy === 'approve' ? 'Approving…' : 'Approve and create bookings'}
              </button>
            </div>
          </>
        )}
      </div>
    );
  }

  private renderDetail(r: GroupRequest): React.ReactNode {
    const { busy, declineReason, paymentRef, detailError, detailMessage } = this.state;
    const st = groupRequestStatus(r.status);
    const open = r.status === 'submitted' || r.status === 'under_review';
    const hasPaid = r.bookings.some((b) => b.status === 'confirmed' || b.status === 'checked_in');
    const unpaid = r.bookings.some((b) => b.status === 'pending' || b.status === 'expired');
    const fact = (label: string, value: React.ReactNode) => (
      <div className="col-sm-6 col-lg-4"><div className="fact"><span className="label">{label}</span>{value}</div></div>
    );
    return (
      <div className="card border-0 shadow-sm mt-4">
        <div className="card-header bg-white d-flex justify-content-between align-items-center gap-2 py-3">
          <h2 className="h4 mb-0"><span className="ref">{r.reference}</span> · {r.organisation_name}</h2>
          <button className="btn btn-sm btn-light" onClick={() => this.setState({ selected: null })}>
            <i className="bi bi-x-lg me-1" aria-hidden="true" /> Close
          </button>
        </div>
        <div className="card-body">
          {detailMessage && <div className="alert alert-success">{detailMessage}</div>}
          {detailError && <div className="alert alert-danger">{detailError}</div>}
          <div className="row g-2 mb-3">
            {fact('Status', <span className={`badge ${st.bg}`}>{st.label}</span>)}
            {fact('Place', <>{r.museum_name}<div className="small text-muted">{r.city_name}</div></>)}
            {fact('Group', <>{r.participants} + {r.escorts} escorts<div className="small text-muted">{r.group_type_label}{r.needs_guide ? ' · guide requested' : ''}</div></>)}
            {fact('Preferred', <>{formatDate(r.preferred_date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}<div className="small text-muted">{r.preferred_time_label}{r.alternative_date ? ` · alt. ${formatDate(r.alternative_date)}` : ''}</div></>)}
            {fact('Contact', <>{r.contact_name}<div className="small"><a href={`mailto:${r.contact_email}`}>{r.contact_email}</a> · <a href={`tel:${r.contact_phone}`}>{r.contact_phone}</a></div></>)}
            {fact('Requested', <>{formatDateTime(r.created_at)}<div className="small text-muted">{r.requester_email}</div></>)}
            {r.decided_at && fact('Decided', <>{formatDateTime(r.decided_at)}<div className="small text-muted">{r.decided_by_email}</div></>)}
            {r.quoted_total !== null && fact('Quote', <>{formatINR(r.quoted_total)}<div className="small text-muted">{r.discount_percent ?? 0}% off · {r.payment_mode_label}</div></>)}
            {r.pay_by && fact('Pay by', formatDateTime(r.pay_by))}
          </div>
          {r.notes && <div className="alert alert-light border small"><strong>Visitor notes:</strong> {r.notes}</div>}
          {r.staff_notes && !open && <div className="alert alert-light border small"><strong>Staff notes:</strong> {r.staff_notes}</div>}

          {r.status === 'submitted' && (
            <button type="button" className="btn btn-sm btn-outline-secondary mb-3" disabled={busy !== ''} onClick={this.markReview}>
              <i className="bi bi-clipboard-check me-1" aria-hidden="true" />Mark under review
            </button>
          )}

          {open && this.renderPlanner(r)}

          {r.bookings.length > 0 && (
            <div className="mb-3">
              <h3 className="h5">Bookings</h3>
              <div className="table-responsive">
                <table className="table table-sm align-middle mb-0">
                  <thead className="table-light">
                    <tr><th>Reference</th><th>Visit</th><th className="text-end">People</th><th className="text-end">Amount</th><th>Status</th><th>Payment</th></tr>
                  </thead>
                  <tbody>
                    {r.bookings.map((b) => (
                      <tr key={b.reference}>
                        <td className="ref">{b.reference}</td>
                        <td>{formatDate(b.visit_date)} <span className="text-muted small">{formatTime(b.slot_start)} – {formatTime(b.slot_end)}</span></td>
                        <td className="text-end">{b.total_visitors}{b.escort_count > 0 && <span className="text-muted small"> (incl. {b.escort_count} escorts)</span>}</td>
                        <td className="text-end">{formatINR(b.total_amount)}</td>
                        <td><StatusBadge status={b.status} /></td>
                        <td className="small text-muted">{b.payment_method ? `${b.payment_method.replace('_', ' ')} ${b.payment_id}` : b.pay_by ? `due ${formatDateTime(b.pay_by)}` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="row g-3">
            {(r.status === 'approved' || r.status === 'expired') && unpaid && (
              <div className="col-lg-6">
                <div className="border rounded p-3 h-100">
                  <h3 className="h6"><i className="bi bi-bank me-1" aria-hidden="true" />Record bank transfer</h3>
                  <input className="form-control form-control-sm mb-2" placeholder="UTR / transfer reference (optional)" maxLength={40} value={paymentRef} onChange={(e) => this.setState({ paymentRef: e.target.value })} aria-label="Transfer reference" />
                  <button type="button" className="btn btn-sm btn-success" disabled={busy !== ''} onClick={this.markPaid}>
                    <i className="bi bi-cash-stack me-1" aria-hidden="true" />{busy === 'paid' ? 'Saving…' : 'Mark paid'}
                  </button>
                </div>
              </div>
            )}
            {(open || (r.status === 'approved' && !hasPaid)) && (
              <div className="col-lg-6">
                <div className="border rounded p-3 h-100">
                  <h3 className="h6"><i className="bi bi-x-circle me-1" aria-hidden="true" />Decline</h3>
                  <textarea className="form-control form-control-sm mb-2" rows={2} placeholder="Reason shown to the visitor" value={declineReason} onChange={(e) => this.setState({ declineReason: e.target.value })} aria-label="Decline reason" />
                  <button type="button" className="btn btn-sm btn-outline-danger" disabled={busy !== ''} onClick={this.decline}>
                    {busy === 'decline' ? 'Declining…' : 'Decline request'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { data, page, status, museum, date, search, selected, error } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Group requests</h1>
          <span className="text-muted small">Groups larger than the instant-booking limit</span>
        </div>
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2 align-items-end">
              <div className="col-12 col-xl-3">
                <input className="form-control" placeholder="Organisation, contact, email, phone…" value={search} onChange={(e) => this.setState({ search: e.target.value, page: 1 })} aria-label="Search requests" />
              </div>
              <div className="col-sm-6 col-xl-2">
                <select className="form-select" value={status} onChange={(e) => this.setState({ status: e.target.value, page: 1 })} aria-label="Status">
                  <option value="open">Open (to review)</option>
                  <option value="">All statuses</option>
                  {GROUP_REQUEST_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
              <div className="col-sm-6 col-xl-2">
                <input type="date" className="form-control" value={date} onChange={(e) => this.setState({ date: e.target.value, page: 1 })} aria-label="Preferred date" />
              </div>
              <div className="col-sm-9 col-xl-4">
                <MuseumPicker filter value={museum} label="Place" clearable onChange={(slug) => this.setState({ museum: slug, page: 1 })} />
              </div>
              <div className="col-sm-3 col-xl-1 d-grid">
                <button className="btn btn-light" onClick={() => this.setState({ search: '', status: 'open', date: '', museum: '', page: 1 })} title="Reset filters" aria-label="Reset filters">
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
          <Empty title="No group requests found" />
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0">
                  <thead className="table-light">
                    <tr><th>Request</th><th>Group</th><th>Place</th><th>Preferred</th><th className="text-end">People</th><th>Status</th><th /></tr>
                  </thead>
                  <tbody>
                    {data.results.map((r) => {
                      const st = groupRequestStatus(r.status);
                      return (
                        <tr key={r.id} className={selected?.id === r.id ? 'table-active' : undefined}>
                          <td><span className="ref">{r.reference}</span><div className="text-muted small">{formatDateTime(r.created_at)}</div></td>
                          <td>{r.organisation_name}<div className="text-muted small">{r.group_type_label} · {r.contact_name}</div></td>
                          <td>{r.museum_name}<div className="text-muted small">{r.city_name}</div></td>
                          <td>{formatDate(r.preferred_date)}<div className="text-muted small">{r.preferred_time_label}</div></td>
                          <td className="text-end">{r.participants}{r.escorts > 0 && <div className="text-muted small">+{r.escorts}</div>}</td>
                          <td><span className={`badge ${st.bg}`}>{st.label}</span></td>
                          <td className="text-end"><button className="btn btn-sm btn-light" onClick={() => this.select(r)}>Open</button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mt-3">
              <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />
            </div>
          </>
        )}

        {selected && this.renderDetail(selected)}
      </div>
    );
  }
}

export default GroupRequestsPage;
