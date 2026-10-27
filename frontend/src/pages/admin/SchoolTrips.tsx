import * as React from 'react';
import { errorMessage } from '../../api/client';
import {
  approveTrip,
  completeTrip,
  declineTrip,
  listSchools,
  listTrips,
  rejectSchool,
  SCHOOL_STATUS_BG,
  TRIP_STATUSES,
  tripEstimate,
  tripSlots,
  tripStatus,
  verifySchool,
} from '../../api/schools';
import type { Paginated, School, SchoolEstimate, SchoolTrip, SchoolTripSlots } from '../../api/types';
import { Empty, Loader, Pagination, StatusBadge } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDate, formatDateTime, formatINR, formatTime } from '../../utils/format';

type Tab = 'trips' | 'schools';

interface SchoolTripsState {
  tab: Tab;
  // trips
  data: Paginated<SchoolTrip> | null;
  page: number;
  status: string;
  museum: string;
  date: string;
  search: string;
  reload: number;
  error: string;
  selected: SchoolTrip | null;
  approveDate: string;
  slot: string;
  quote: string;
  note: string;
  declineReason: string;
  estimate: SchoolEstimate | null;
  slots: SchoolTripSlots | null;
  busy: '' | 'approve' | 'decline' | 'complete';
  detailError: string;
  detailMessage: string;
  // schools
  schools: Paginated<School> | null;
  schoolPage: number;
  schoolStatus: string;
  schoolSearch: string;
  schoolError: string;
  schoolBusy: number | null;
  rejectFor: number | null;
  rejectReason: string;
}

/** Staff/admin: class trip requests from schools (approve, decline, complete) and, for admins, school verification. */
class SchoolTripsPage extends React.Component<WithAuthProps, SchoolTripsState> {
  public state: SchoolTripsState = {
    tab: 'trips',
    data: null, page: 1, status: 'submitted', museum: '', date: '', search: '', reload: 0, error: '',
    selected: null, approveDate: '', slot: '', quote: '', note: '', declineReason: '', estimate: null, slots: null,
    busy: '', detailError: '', detailMessage: '',
    schools: null, schoolPage: 1, schoolStatus: 'pending', schoolSearch: '', schoolError: '', schoolBusy: null,
    rejectFor: null, rejectReason: '',
  };

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_prevProps: WithAuthProps, prev: SchoolTripsState): void {
    const s = this.state;
    if (s.tab !== prev.tab || s.page !== prev.page || s.status !== prev.status || s.museum !== prev.museum || s.date !== prev.date
      || s.search !== prev.search || s.reload !== prev.reload || s.schoolPage !== prev.schoolPage
      || s.schoolStatus !== prev.schoolStatus || s.schoolSearch !== prev.schoolSearch) {
      this.scheduleLoad();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private isAdmin(): boolean {
    return !!this.props.auth.user?.is_admin_role;
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => (this.state.tab === 'trips' ? this.loadTrips() : this.loadSchools()), 250);
  }

  private loadTrips(): void {
    const { page, status, museum, date, search } = this.state;
    listTrips({ page, status: status || undefined, museum: museum || undefined, date: date || undefined, search: search || undefined })
      .then((data) => this.mounted && this.setState({ data, error: '' }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err), data: { count: 0, next: null, previous: null, results: [] } }));
  }

  private loadSchools(): void {
    const { schoolPage, schoolStatus, schoolSearch } = this.state;
    listSchools({ page: schoolPage, status: schoolStatus || undefined, search: schoolSearch || undefined })
      .then((schools) => this.mounted && this.setState({ schools, schoolError: '' }))
      .catch((err) => this.mounted && this.setState({ schoolError: errorMessage(err), schools: { count: 0, next: null, previous: null, results: [] } }));
  }

  // --- trip detail ------------------------------------------------------------------------------------

  private select = (trip: SchoolTrip): void => {
    this.setState({
      selected: trip, approveDate: trip.preferred_date, slot: '', quote: '', note: trip.staff_note, declineReason: '',
      estimate: null, slots: null, detailError: '', detailMessage: '',
    });
    if (trip.status === 'submitted') this.loadPlanning(trip, trip.preferred_date);
  };

  private loadPlanning(trip: SchoolTrip, date: string): void {
    Promise.all([tripEstimate(trip.id, date), tripSlots(trip.id, date)])
      .then(([estimate, slots]) => {
        if (!this.mounted || this.state.selected?.id !== trip.id) return;
        this.setState({ estimate, slots, quote: estimate.total });
      })
      .catch((err) => this.mounted && this.setState({ detailError: errorMessage(err) }));
  }

  private pickDate = (date: string): void => {
    const { selected } = this.state;
    if (!selected) return;
    this.setState({ approveDate: date, slot: '', estimate: null, slots: null });
    this.loadPlanning(selected, date);
  };

  private replace(updated: SchoolTrip, message = ''): void {
    this.setState((s) => ({
      selected: updated,
      busy: '',
      detailError: '',
      detailMessage: message,
      data: s.data && { ...s.data, results: s.data.results.map((x) => (x.id === updated.id ? updated : x)) },
    }));
  }

  private approve = async (): Promise<void> => {
    const { selected, approveDate, slot, quote, note, estimate } = this.state;
    if (!selected) return;
    this.setState({ busy: 'approve', detailError: '', detailMessage: '' });
    try {
      const quoted = quote.trim() !== '' && estimate && Number(quote) !== Number(estimate.total) ? quote.trim() : null;
      const updated = await approveTrip(selected.id, { date: approveDate, slot: slot ? Number(slot) : null, quoted_amount: quoted, staff_note: note });
      if (this.mounted) this.replace(updated, `Approved: booking ${updated.booking?.reference ?? ''} created for ${formatINR(updated.quoted_amount)}. The teacher has been emailed.`);
    } catch (err) {
      if (this.mounted) this.setState({ busy: '', detailError: errorMessage(err) });
    }
  };

  private decline = async (): Promise<void> => {
    const { selected, declineReason } = this.state;
    if (!selected) return;
    if (!declineReason.trim()) {
      this.setState({ detailError: 'Give the teacher a reason for declining.' });
      return;
    }
    if (!window.confirm(`Decline ${selected.reference}? Any unpaid booking will be released.`)) return;
    this.setState({ busy: 'decline', detailError: '', detailMessage: '' });
    try {
      const updated = await declineTrip(selected.id, declineReason.trim());
      if (this.mounted) this.replace(updated, 'Trip declined. The teacher has been emailed.');
    } catch (err) {
      if (this.mounted) this.setState({ busy: '', detailError: errorMessage(err) });
    }
  };

  private complete = async (): Promise<void> => {
    const { selected } = this.state;
    if (!selected) return;
    this.setState({ busy: 'complete', detailError: '', detailMessage: '' });
    try {
      const updated = await completeTrip(selected.id);
      if (this.mounted) this.replace(updated, 'Marked completed.');
    } catch (err) {
      if (this.mounted) this.setState({ busy: '', detailError: errorMessage(err) });
    }
  };

  // --- schools ----------------------------------------------------------------------------------------

  private replaceSchool(updated: School): void {
    this.setState((s) => ({
      schoolBusy: null,
      rejectFor: null,
      rejectReason: '',
      schools: s.schools && { ...s.schools, results: s.schools.results.map((x) => (x.id === updated.id ? updated : x)) },
    }));
  }

  private verify = async (school: School): Promise<void> => {
    this.setState({ schoolBusy: school.id, schoolError: '' });
    try {
      const updated = await verifySchool(school.id);
      if (this.mounted) this.replaceSchool(updated);
    } catch (err) {
      if (this.mounted) this.setState({ schoolBusy: null, schoolError: errorMessage(err) });
    }
  };

  private reject = async (school: School): Promise<void> => {
    const reason = this.state.rejectReason.trim();
    if (!reason) {
      this.setState({ schoolError: 'Give the teacher a reason for rejecting the school.' });
      return;
    }
    this.setState({ schoolBusy: school.id, schoolError: '' });
    try {
      const updated = await rejectSchool(school.id, reason);
      if (this.mounted) this.replaceSchool(updated);
    } catch (err) {
      if (this.mounted) this.setState({ schoolBusy: null, schoolError: errorMessage(err) });
    }
  };

  // --- render -----------------------------------------------------------------------------------------

  private renderApprove(trip: SchoolTrip): React.ReactNode {
    const { approveDate, slot, quote, note, estimate, slots, busy } = this.state;
    const dates = [trip.preferred_date, ...(trip.alternative_date ? [trip.alternative_date] : [])];
    return (
      <div className="border rounded p-3 mb-3">
        <h3 className="h5 mb-3"><i className="bi bi-check-circle me-2" aria-hidden="true" />Approve</h3>
        <div className="row g-2">
          <div className="col-sm-6 col-lg-4">
            <label htmlFor="st-adate" className="form-label small mb-1">Visit date</label>
            <select id="st-adate" className="form-select" value={approveDate} onChange={(e) => this.pickDate(e.target.value)}>
              {dates.map((d, i) => <option key={d} value={d}>{formatDate(d, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}{i ? ' (alternative)' : ' (preferred)'}</option>)}
            </select>
          </div>
          <div className="col-sm-6 col-lg-4">
            <label htmlFor="st-aslot" className="form-label small mb-1">Slot</label>
            <select id="st-aslot" className="form-select" value={slot} onChange={(e) => this.setState({ slot: e.target.value })}>
              <option value="">First with room ({trip.slot_preference_label.toLowerCase()} first)</option>
              {slots?.slots.map((s) => (
                <option key={s.slot_id} value={s.slot_id} disabled={s.closed}>
                  {formatTime(s.start)} – {formatTime(s.end)} · group room {s.group_room}{s.closed ? ' (closed)' : s.group_room < (slots?.people ?? 0) ? ' (too small)' : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="col-sm-6 col-lg-4">
            <label htmlFor="st-quote" className="form-label small mb-1">Quoted amount (₹)</label>
            <input id="st-quote" type="number" min={0} max={estimate ? Number(estimate.subtotal) : undefined} step="1" className="form-control" value={quote} onChange={(e) => this.setState({ quote: e.target.value })} />
          </div>
          <div className="col-12">
            <label htmlFor="st-note" className="form-label small mb-1">Note to the teacher <span className="text-muted">(in the approval email)</span></label>
            <textarea id="st-note" className="form-control" rows={2} value={note} onChange={(e) => this.setState({ note: e.target.value })} />
          </div>
        </div>
        {slots?.date_error && <div className="alert alert-warning small py-2 mt-2 mb-0">{slots.date_error}</div>}
        {estimate && (
          <div className="small text-muted mt-2">
            {estimate.lines.map((l) => `${l.quantity} × ${l.name} @ ${formatINR(l.unit_price)}`).join(' · ')}
            {estimate.free_teachers > 0 && ` · ${estimate.free_teachers} teacher(s) free`}
            {' · '}tickets {formatINR(estimate.subtotal)}, school discount {estimate.discount_percent}% → <strong>{formatINR(estimate.total)}</strong>.
            {' '}{slots && `${slots.people} people need one slot with that much group room.`}
          </div>
        )}
        <div className="d-flex justify-content-end mt-3">
          <button type="button" className="btn btn-success" disabled={busy !== '' || !estimate} onClick={this.approve}>
            <i className="bi bi-check-circle me-1" aria-hidden="true" />{busy === 'approve' ? 'Approving…' : 'Approve and create booking'}
          </button>
        </div>
      </div>
    );
  }

  private renderDetail(trip: SchoolTrip): React.ReactNode {
    const { busy, declineReason, detailError, detailMessage } = this.state;
    const st = tripStatus(trip.status);
    const b = trip.booking;
    const paid = !!b && (b.status === 'confirmed' || b.status === 'checked_in');
    const fact = (label: string, value: React.ReactNode) => (
      <div className="col-sm-6 col-lg-4"><div className="fact"><span className="label">{label}</span>{value}</div></div>
    );
    return (
      <div className="card border-0 shadow-sm mt-4">
        <div className="card-header bg-white d-flex justify-content-between align-items-center gap-2 py-3">
          <h2 className="h4 mb-0"><span className="ref">{trip.reference}</span> · {trip.school_name}</h2>
          <button className="btn btn-sm btn-light" onClick={() => this.setState({ selected: null })}><i className="bi bi-x-lg me-1" aria-hidden="true" />Close</button>
        </div>
        <div className="card-body">
          {detailMessage && <div className="alert alert-success">{detailMessage}</div>}
          {detailError && <div className="alert alert-danger">{detailError}</div>}
          <div className="row g-2 mb-3">
            {fact('Status', <span className={`badge ${st.bg}`}>{trip.status_label}</span>)}
            {fact('Place', <>{trip.museum_name}<div className="small text-muted">{trip.city_name}</div></>)}
            {fact('School', <>{trip.school_name}<div className="small text-muted">{trip.school_board} · {trip.school_city}</div></>)}
            {fact('Class', <>{trip.grades}: {trip.students} students<div className="small text-muted">{trip.teachers} teachers ({trip.free_teachers} free) · {trip.helpers} helpers{trip.young_students ? ` · ${trip.young_students} on child ticket` : ''}</div></>)}
            {fact('Dates', <>{formatDate(trip.preferred_date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}<div className="small text-muted">{trip.slot_preference_label}{trip.alternative_date ? ` · alt. ${formatDate(trip.alternative_date)}` : ''}</div></>)}
            {fact('Contact', <>{trip.contact_name}<div className="small"><a href={`mailto:${trip.contact_email}`}>{trip.contact_email}</a> · <a href={`tel:${trip.contact_phone}`}>{trip.contact_phone}</a></div></>)}
            {fact('Guide', trip.guide_language ? trip.guide_language_label : 'Not needed')}
            {fact('Estimate / quote', <>{formatINR(trip.estimated_amount)}{trip.quoted_amount !== null && <div className="small">Quoted <strong>{formatINR(trip.quoted_amount)}</strong></div>}</>)}
            {trip.decided_at && fact('Decided', <>{formatDateTime(trip.decided_at)}<div className="small text-muted">{trip.decided_by_email}</div></>)}
          </div>
          {trip.accessibility_needs && <div className="alert alert-info small"><strong>Accessibility:</strong> {trip.accessibility_needs}</div>}
          {trip.notes && <div className="alert alert-light border small"><strong>Teacher notes:</strong> {trip.notes}</div>}
          {trip.staff_note && trip.status !== 'submitted' && <div className="alert alert-light border small"><strong>Staff note:</strong> {trip.staff_note}</div>}

          {b && (
            <div className="table-responsive mb-3">
              <table className="table table-sm align-middle mb-0">
                <thead className="table-light"><tr><th>Booking</th><th>Visit</th><th className="text-end">People</th><th className="text-end">Amount</th><th>Status</th><th>Payment</th></tr></thead>
                <tbody>
                  <tr>
                    <td className="ref">{b.reference}</td>
                    <td>{formatDate(b.visit_date)} <span className="text-muted small">{formatTime(b.slot_start)} – {formatTime(b.slot_end)}</span></td>
                    <td className="text-end">{b.total_visitors}{b.escort_count > 0 && <span className="text-muted small"> (incl. {b.escort_count} free)</span>}</td>
                    <td className="text-end">{formatINR(b.total_amount)}</td>
                    <td><StatusBadge status={b.status} /></td>
                    <td className="small text-muted">{b.payment_method ? `${b.payment_method.replace('_', ' ')} ${b.payment_id}` : b.pay_by ? `due ${formatDateTime(b.pay_by)}` : ''}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          {trip.status === 'submitted' && this.renderApprove(trip)}

          <div className="row g-3">
            {(trip.status === 'submitted' || (trip.status === 'approved' && !paid)) && (
              <div className="col-lg-6">
                <div className="border rounded p-3 h-100">
                  <h3 className="h6"><i className="bi bi-x-circle me-1" aria-hidden="true" />Decline</h3>
                  <textarea className="form-control form-control-sm mb-2" rows={2} placeholder="Reason shown to the teacher" value={declineReason} onChange={(e) => this.setState({ declineReason: e.target.value })} aria-label="Decline reason" />
                  <button type="button" className="btn btn-sm btn-outline-danger" disabled={busy !== ''} onClick={this.decline}>{busy === 'decline' ? 'Declining…' : 'Decline trip'}</button>
                </div>
              </div>
            )}
            {trip.status === 'approved' && paid && (
              <div className="col-lg-6">
                <div className="border rounded p-3 h-100">
                  <h3 className="h6"><i className="bi bi-flag me-1" aria-hidden="true" />After the visit</h3>
                  <button type="button" className="btn btn-sm btn-success" disabled={busy !== ''} onClick={this.complete}>{busy === 'complete' ? 'Saving…' : 'Mark completed'}</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  private renderTrips(): React.ReactNode {
    const { data, page, status, museum, date, search, selected, error } = this.state;
    return (
      <>
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2 align-items-end">
              <div className="col-12 col-xl-3">
                <input className="form-control" placeholder="School, teacher, email, class…" value={search} onChange={(e) => this.setState({ search: e.target.value, page: 1 })} aria-label="Search trips" />
              </div>
              <div className="col-sm-6 col-xl-2">
                <select className="form-select" value={status} onChange={(e) => this.setState({ status: e.target.value, page: 1 })} aria-label="Status">
                  <option value="">All statuses</option>
                  {TRIP_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
              <div className="col-sm-6 col-xl-2">
                <input type="date" className="form-control" value={date} onChange={(e) => this.setState({ date: e.target.value, page: 1 })} aria-label="Visit date" title="Preferred, alternative or approved date" />
              </div>
              <div className="col-sm-9 col-xl-4">
                <MuseumPicker filter value={museum} label="Place" clearable onChange={(slug) => this.setState({ museum: slug, page: 1 })} />
              </div>
              <div className="col-sm-3 col-xl-1 d-grid">
                <button className="btn btn-light" onClick={() => this.setState({ search: '', status: 'submitted', date: '', museum: '', page: 1 })} title="Reset filters" aria-label="Reset filters">
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
          <Empty title="No school trips found" />
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0">
                  <thead className="table-light">
                    <tr><th>Trip</th><th>School</th><th>Place</th><th>Date</th><th className="text-end">Class</th><th>Status</th><th /></tr>
                  </thead>
                  <tbody>
                    {data.results.map((tr) => (
                      <tr key={tr.id} className={selected?.id === tr.id ? 'table-active' : undefined}>
                        <td><span className="ref">{tr.reference}</span><div className="text-muted small">{formatDateTime(tr.created_at)}</div></td>
                        <td>{tr.school_name}<div className="text-muted small">{tr.contact_name}</div></td>
                        <td>{tr.museum_name}<div className="text-muted small">{tr.city_name}</div></td>
                        <td>{formatDate(tr.approved_date ?? tr.preferred_date)}<div className="text-muted small">{tr.slot_preference_label}{!tr.approved_date && tr.alternative_date ? ` · alt. ${formatDate(tr.alternative_date)}` : ''}</div></td>
                        <td className="text-end">{tr.students}<div className="text-muted small">+{tr.teachers + tr.helpers} adults</div></td>
                        <td><span className={`badge ${tripStatus(tr.status).bg}`}>{tr.status_label}</span>{tr.booking && <div className="mt-1"><StatusBadge status={tr.booking.status} /></div>}</td>
                        <td className="text-end"><button className="btn btn-sm btn-light" onClick={() => this.select(tr)}>Open</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mt-3"><Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} /></div>
          </>
        )}
        {selected && this.renderDetail(selected)}
      </>
    );
  }

  private renderSchools(): React.ReactNode {
    const { schools, schoolPage, schoolStatus, schoolSearch, schoolError, schoolBusy, rejectFor, rejectReason } = this.state;
    return (
      <>
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-md-8">
                <input className="form-control" placeholder="School, city, UDISE, teacher email…" value={schoolSearch} onChange={(e) => this.setState({ schoolSearch: e.target.value, schoolPage: 1 })} aria-label="Search schools" />
              </div>
              <div className="col-md-4">
                <select className="form-select" value={schoolStatus} onChange={(e) => this.setState({ schoolStatus: e.target.value, schoolPage: 1 })} aria-label="Status">
                  <option value="">All statuses</option>
                  <option value="pending">Pending verification</option>
                  <option value="verified">Verified</option>
                  <option value="rejected">Rejected</option>
                </select>
              </div>
            </div>
          </div>
        </div>
        {schoolError && <div className="alert alert-danger">{schoolError}</div>}
        {schools === null ? (
          <Loader />
        ) : schools.count === 0 ? (
          <Empty title="No schools found" />
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table align-middle mb-0">
                  <thead className="table-light">
                    <tr><th>School</th><th>Board / UDISE</th><th>Principal / phone</th><th>Contact teacher</th><th>Status</th><th className="text-end">Actions</th></tr>
                  </thead>
                  <tbody>
                    {schools.results.map((s) => (
                      <tr key={s.id}>
                        <td>{s.name}<div className="text-muted small">{s.address}, {s.city}, {s.state_name}</div><div className="text-muted small">Registered {formatDate(s.created_at)} · {s.trip_count} trip(s)</div></td>
                        <td>{s.board_label}<div className="text-muted small">{s.udise_code || 'No UDISE'}</div></td>
                        <td>{s.principal_name}<div className="small"><a href={`tel:${s.phone}`}>{s.phone}</a></div></td>
                        <td>{s.contact_name}<div className="small"><a href={`mailto:${s.contact_email}`}>{s.contact_email}</a></div><div className="small text-muted">{s.owner_email}</div></td>
                        <td>
                          <span className={`badge ${SCHOOL_STATUS_BG[s.status]}`}>{s.status_label}</span>
                          {s.rejection_reason && <div className="small text-muted mt-1">{s.rejection_reason}</div>}
                          {s.verified_by_email && <div className="small text-muted">by {s.verified_by_email}</div>}
                        </td>
                        <td className="text-end" style={{ minWidth: 200 }}>
                          {rejectFor === s.id ? (
                            <div>
                              <textarea className="form-control form-control-sm mb-1" rows={2} placeholder="Reason shown to the teacher" value={rejectReason} onChange={(e) => this.setState({ rejectReason: e.target.value })} aria-label="Reject reason" />
                              <button className="btn btn-sm btn-danger me-1" disabled={schoolBusy === s.id} onClick={() => this.reject(s)}>Reject</button>
                              <button className="btn btn-sm btn-light" onClick={() => this.setState({ rejectFor: null, rejectReason: '' })}>Cancel</button>
                            </div>
                          ) : (
                            <>
                              {s.status !== 'verified' && (
                                <button className="btn btn-sm btn-success me-1" disabled={schoolBusy === s.id} onClick={() => this.verify(s)}>
                                  <i className="bi bi-patch-check me-1" aria-hidden="true" />Verify
                                </button>
                              )}
                              {s.status !== 'rejected' && (
                                <button className="btn btn-sm btn-outline-danger" disabled={schoolBusy === s.id} onClick={() => this.setState({ rejectFor: s.id, rejectReason: '' })}>Reject</button>
                              )}
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mt-3"><Pagination page={schoolPage} count={schools.count} onChange={(p) => this.setState({ schoolPage: p })} /></div>
          </>
        )}
      </>
    );
  }

  public render(): React.ReactNode {
    const { tab } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
          <h1 className="h2 mb-0">School trips</h1>
          <span className="text-muted small">Class visits requested by verified schools</span>
        </div>
        {this.isAdmin() && (
          <ul className="nav nav-tabs mb-3">
            <li className="nav-item">
              <button type="button" className={`nav-link ${tab === 'trips' ? 'active' : ''}`} onClick={() => this.setState({ tab: 'trips' })}>
                <i className="bi bi-calendar-event me-1" aria-hidden="true" />Trips
              </button>
            </li>
            <li className="nav-item">
              <button type="button" className={`nav-link ${tab === 'schools' ? 'active' : ''}`} onClick={() => this.setState({ tab: 'schools' })}>
                <i className="bi bi-building me-1" aria-hidden="true" />Schools
              </button>
            </li>
          </ul>
        )}
        {tab === 'schools' && this.isAdmin() ? this.renderSchools() : this.renderTrips()}
      </div>
    );
  }
}

export default withAuth(SchoolTripsPage);
