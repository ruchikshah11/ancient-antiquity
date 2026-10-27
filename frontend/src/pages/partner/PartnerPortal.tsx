import * as React from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../api/client';
import { getPartnerMe, getPartnerOverview, getPartnerReviews, getPartnerSettlements, getPartnerTrend } from '../../api/partner';
import type {
  PartnerFigures, PartnerMe, PartnerOverview, PartnerPeriod, PartnerReview, PartnerSettlement, PartnerTrendDay,
} from '../../api/types';
import { DayTick, tickEvery } from '../../components/DayTick';
import { Empty, Loader } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDate, formatINR, formatNumber } from '../../utils/format';

/** Read-only portal for a place's management (role partner). English only, like the admin panel. */

const PERIODS: { id: PartnerPeriod; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'this_month', label: 'This month' },
  { id: 'last_month', label: 'Last month' },
];

interface KpiProps {
  label: string;
  value: string;
  sub?: string;
  icon: string;
}

class Kpi extends React.Component<KpiProps> {
  public render(): React.ReactNode {
    const { label, value, sub, icon } = this.props;
    return (
      <div className="card border-0 shadow-sm stat-card h-100">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start">
            <div className="text-muted small">{label}</div>
            <i className={`bi ${icon} text-accent`} aria-hidden="true" />
          </div>
          <div className="stat-value">{value}</div>
          {sub && <div className="text-muted small">{sub}</div>}
        </div>
      </div>
    );
  }
}

interface TrendChartProps {
  data: PartnerTrendDay[];
}

/** Single-series column chart (same markup as the admin dashboard's daily chart): visitors per visit day. */
class TrendChart extends React.Component<TrendChartProps> {
  public render(): React.ReactNode {
    const { data } = this.props;
    const max = Math.max(1, ...data.map((d) => d.visitors));
    const every = tickEvery(data.length);
    return (
      <>
        <div className="chart-bars" role="img" aria-label={`Visitors per day, last ${data.length} days`}>
          {data.map((d, i) => (
            <div className="col-bar" key={d.date} tabIndex={0}>
              <span className="tip">
                {formatDate(d.date, { day: 'numeric', month: 'short' })}: {formatNumber(d.visitors)} visitor{d.visitors === 1 ? '' : 's'} · {formatINR(d.revenue)} paid
              </span>
              <div className="bar" style={{ height: `${(d.visitors / max) * 100}%` }} />
              <DayTick dates={data.map((x) => x.date)} index={i} every={every} />
            </div>
          ))}
        </div>
        <details className="mt-3">
          <summary className="text-muted small" style={{ cursor: 'pointer' }}>View as table</summary>
          <div className="table-responsive mt-2">
            <table className="table table-sm mb-0">
              <thead className="table-light"><tr><th>Date</th><th className="text-end">Visitors</th><th className="text-end">Revenue paid</th></tr></thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.date}><td>{formatDate(d.date)}</td><td className="text-end">{formatNumber(d.visitors)}</td><td className="text-end">{formatINR(d.revenue)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </>
    );
  }
}

interface Props extends WithAuthProps {}

interface State {
  me: PartnerMe | null;
  museum: string;
  period: PartnerPeriod;
  days: 30 | 90;
  overview: PartnerOverview | null;
  trend: PartnerTrendDay[] | null;
  reviews: PartnerReview[];
  reviewsTotal: number;
  reviewsNext: number | null;
  settlements: PartnerSettlement[] | null;
  error: string;
}

class PartnerPortalBase extends React.Component<Props, State> {
  public state: State = {
    me: null, museum: '', period: 'today', days: 30, overview: null, trend: null, reviews: [], reviewsTotal: 0,
    reviewsNext: null, settlements: null, error: '',
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    if (this.props.auth.user?.role !== 'partner') return;
    getPartnerMe()
      .then((me) => this.mounted && this.setState({ me }, this.loadAll))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private fail = (err: unknown): void => {
    if (this.mounted) this.setState({ error: errorMessage(err) });
  };

  private loadAll = (): void => {
    const { museum } = this.state;
    this.setState({ overview: null, settlements: null, error: '' });
    getPartnerOverview(museum).then((overview) => this.mounted && this.setState({ overview })).catch(this.fail);
    getPartnerSettlements(museum).then((settlements) => this.mounted && this.setState({ settlements })).catch(this.fail);
    this.loadTrend();
    this.loadReviews(0);
  };

  private loadTrend = (): void => {
    this.setState({ trend: null });
    getPartnerTrend(this.state.days, this.state.museum).then((t) => this.mounted && this.setState({ trend: t.daily })).catch(this.fail);
  };

  private loadReviews = (offset: number): void => {
    getPartnerReviews(this.state.museum, offset, 10)
      .then((r) => this.mounted && this.setState((s) => ({
        reviews: offset ? [...s.reviews, ...r.results] : r.results, reviewsTotal: r.count, reviewsNext: r.next_offset,
      })))
      .catch(this.fail);
  };

  private renderKpis(f: PartnerFigures): React.ReactNode {
    return (
      <div className="row g-3 mb-4">
        <div className="col-6 col-lg-3"><Kpi label="Visitors" value={formatNumber(f.visitors)} sub="Paid tickets for visits in the period" icon="bi-people" /></div>
        <div className="col-6 col-lg-3"><Kpi label="Bookings" value={formatNumber(f.bookings)} sub="Paid bookings visiting" icon="bi-ticket-perforated" /></div>
        <div className="col-6 col-lg-3"><Kpi label="Revenue" value={formatINR(f.revenue)} sub="Paid in the period (gift vouchers included)" icon="bi-currency-rupee" /></div>
        <div className="col-6 col-lg-3"><Kpi label="Refunds" value={formatINR(f.refunds)} sub="Refunded in the period" icon="bi-arrow-counterclockwise" /></div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { user } = this.props.auth;
    const { me, museum, period, days, overview, trend, reviews, reviewsTotal, reviewsNext, settlements, error } = this.state;
    if (user && user.role !== 'partner') {
      return (
        <div className="container page py-5">
          <Empty title="This page is for place partners" />
          <p className="text-center"><Link to="/">Back to home</Link></p>
        </div>
      );
    }
    if (!me) return error ? <div className="container py-5"><div className="alert alert-danger">{error}</div></div> : <Loader />;
    const periodInfo = overview?.periods[period];

    return (
      <div className="container page py-4">
        <div className="d-flex justify-content-between align-items-end flex-wrap gap-2 mb-3">
          <div>
            <h1 className="h2 mb-1">Partner portal</h1>
            <p className="text-muted small mb-0">Read-only figures for your places. Questions about payouts? Contact the Ancient Antiquity team.</p>
          </div>
          {me.places.length > 1 && (
            <div>
              <label htmlFor="pp-place" className="form-label small mb-1">Place</label>
              <select id="pp-place" className="form-select" value={museum} onChange={(e) => this.setState({ museum: e.target.value }, this.loadAll)}>
                <option value="">All my places ({me.places.length})</option>
                {me.places.map((p) => <option key={p.slug} value={p.slug}>{p.name}, {p.city_name}</option>)}
              </select>
            </div>
          )}
        </div>
        {error && <div className="alert alert-danger">{error}</div>}
        {me.places.length === 0 ? (
          <Empty title="No places linked yet" />
        ) : (
          <>
            <div className="btn-group mb-3" role="group" aria-label="Period">
              {PERIODS.map((p) => (
                <button key={p.id} type="button" className={`btn btn-sm ${period === p.id ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={period === p.id} onClick={() => this.setState({ period: p.id })}>
                  {p.label}
                </button>
              ))}
            </div>
            {periodInfo && (
              <p className="small text-muted mb-2">
                {periodInfo.from === periodInfo.to ? formatDate(periodInfo.from) : `${formatDate(periodInfo.from)} to ${formatDate(periodInfo.to)}`}
              </p>
            )}
            {overview ? this.renderKpis(overview.totals[period]) : <Loader />}

            {overview && overview.places.length > 1 && (
              <div className="card border-0 shadow-sm mb-4">
                <div className="table-responsive">
                  <table className="table table-hover align-middle mb-0">
                    <thead className="table-light">
                      <tr><th>Place</th><th className="text-end">Visitors</th><th className="text-end">Bookings</th><th className="text-end">Revenue</th><th className="text-end">Refunds</th></tr>
                    </thead>
                    <tbody>
                      {overview.places.map((p) => (
                        <tr key={p.slug}>
                          <td>{p.name} <span className="text-muted small">· {p.city_name}</span></td>
                          <td className="text-end">{formatNumber(p[period].visitors)}</td>
                          <td className="text-end">{formatNumber(p[period].bookings)}</td>
                          <td className="text-end">{formatINR(p[period].revenue)}</td>
                          <td className="text-end">{formatINR(p[period].refunds)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="card border-0 shadow-sm mb-4">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-center flex-wrap gap-2">
                  <h2 className="h5 mb-0">Daily visitors</h2>
                  <div className="btn-group" role="group" aria-label="Range">
                    {([30, 90] as const).map((d) => (
                      <button key={d} type="button" className={`btn btn-sm ${days === d ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={days === d} onClick={() => this.setState({ days: d }, this.loadTrend)}>
                        {d} days
                      </button>
                    ))}
                  </div>
                </div>
                {trend ? <TrendChart data={trend} /> : <Loader />}
              </div>
            </div>

            <div className="row g-4">
              <div className="col-lg-6">
                <div className="card border-0 shadow-sm h-100">
                  <div className="card-body">
                    <h2 className="h5 mb-3">Recent reviews <span className="text-muted small fw-normal">({formatNumber(reviewsTotal)})</span></h2>
                    {reviews.length === 0 ? (
                      <p className="text-muted mb-0">No reviews yet.</p>
                    ) : (
                      <div className="table-responsive">
                        <table className="table table-sm align-middle mb-0">
                          <thead className="table-light"><tr><th>Date</th><th>Place</th><th>Rating</th><th>Review</th><th className="text-end" title="Helpful votes">👍</th></tr></thead>
                          <tbody>
                            {reviews.map((r) => (
                              <tr key={r.id}>
                                <td className="small text-nowrap">{formatDate(r.created_at)}</td>
                                <td className="small">{r.museum_name}</td>
                                <td className="text-nowrap"><span className="text-warning" aria-hidden="true">★</span> {r.rating}</td>
                                <td className="small">
                                  {r.title && <span className="fw-semibold d-block">{r.title}</span>}
                                  {r.comment || <span className="text-muted">—</span>}
                                  <span className="d-block text-muted">{r.user_name}</span>
                                </td>
                                <td className="text-end small">{r.helpful_count}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    {reviewsNext !== null && (
                      <button type="button" className="btn btn-link btn-sm px-0 mt-2" onClick={() => this.loadReviews(reviewsNext)}>Show more</button>
                    )}
                  </div>
                </div>
              </div>
              <div className="col-lg-6">
                <div className="card border-0 shadow-sm h-100">
                  <div className="card-body">
                    <h2 className="h5 mb-1">Settlements and payouts</h2>
                    <p className="text-muted small mb-3">Approved and paid settlements. Net payable is after the platform fee and GST; negative means the place owes the platform (counter cash).</p>
                    {settlements === null ? (
                      <Loader />
                    ) : settlements.length === 0 ? (
                      <p className="text-muted mb-0">No settlements yet.</p>
                    ) : (
                      <div className="table-responsive">
                        <table className="table table-sm align-middle mb-0">
                          <thead className="table-light"><tr><th>Period</th><th>Place</th><th className="text-end">Gross</th><th className="text-end">Net payable</th><th>Status</th></tr></thead>
                          <tbody>
                            {settlements.map((s) => (
                              <tr key={s.id}>
                                <td className="small text-nowrap">{formatDate(s.period_start)} – {formatDate(s.period_end)}</td>
                                <td className="small">{s.museum_name}</td>
                                <td className="text-end small">{formatINR(s.gross_total)}</td>
                                <td className="text-end small fw-semibold">{formatINR(s.net_payable)}</td>
                                <td className="small">
                                  <span className={`badge ${s.status === 'paid' ? 'bg-success' : 'bg-info text-dark'}`}>{s.status_label}</span>
                                  {s.status === 'paid' && (
                                    <span className="d-block text-muted">
                                      {s.paid_at ? formatDate(s.paid_at) : ''}{s.paid_reference ? ` · ${s.paid_reference}` : ''}
                                      {s.payout_account?.account_number ? ` · ${s.payout_account.bank_name} ${s.payout_account.account_number}` : ''}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    );
  }
}

export default withAuth(PartnerPortalBase);
