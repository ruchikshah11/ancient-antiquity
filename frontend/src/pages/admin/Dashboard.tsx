import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import type { Dashboard as DashboardData } from '../../api/types';
import { Loader, StatusBadge } from '../../components/Common';
import { formatDate, formatINR, formatNumber, formatTime } from '../../utils/format';
import { DayTick } from '../../components/DayTick';

interface StatProps {
  label: string;
  value: string;
  sub?: string;
  icon?: string;
}

class Stat extends React.Component<StatProps> {
  public render(): React.ReactNode {
    const { label, value, sub, icon } = this.props;
    return (
      <div className="card border-0 shadow-sm stat-card h-100">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start">
            <div className="text-muted small">{label}</div>
            {icon && <i className={`bi ${icon} text-accent`} aria-hidden="true" />}
          </div>
          <div className="stat-value">{value}</div>
          {sub && <div className="text-muted small">{sub}</div>}
        </div>
      </div>
    );
  }
}

interface DailyChartProps {
  data: DashboardData['daily'];
}

/** Single-series column chart with a hover tooltip per bar. */
class DailyChart extends React.Component<DailyChartProps> {
  public render(): React.ReactNode {
    const { data } = this.props;
    const max = Math.max(1, ...data.map((d) => d.revenue));
    return (
      <>
        <div className="chart-bars" role="img" aria-label="Revenue per day, last 14 days">
          {data.map((d, i) => (
            <div className="col-bar" key={d.date} tabIndex={0}>
              <span className="tip">
                {formatDate(d.date, { day: 'numeric', month: 'short' })}: {formatINR(d.revenue)} · {d.bookings} booking{d.bookings === 1 ? '' : 's'}
              </span>
              <div className="bar" style={{ height: `${(d.revenue / max) * 100}%` }} />
              <DayTick dates={data.map((x) => x.date)} index={i} every={1} />
            </div>
          ))}
        </div>
        <details className="mt-3">
          <summary className="text-muted small" style={{ cursor: 'pointer' }}>View as table</summary>
          <div className="table-responsive mt-2">
            <table className="table table-sm mb-0">
              <thead className="table-light"><tr><th>Date</th><th className="text-end">Bookings</th><th className="text-end">Revenue</th></tr></thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.date}><td>{formatDate(d.date)}</td><td className="text-end">{d.bookings}</td><td className="text-end">{formatINR(d.revenue)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </>
    );
  }
}

interface RankListProps {
  rows: { name: string; value: number; label: string }[];
}

class RankList extends React.Component<RankListProps> {
  public render(): React.ReactNode {
    const { rows } = this.props;
    const max = Math.max(1, ...rows.map((r) => r.value));
    if (rows.length === 0) return <p className="text-muted small mb-0">No paid bookings yet.</p>;
    return (
      <div>
        {rows.map((r) => (
          <div className="hbar" key={r.name} title={`${r.name}: ${r.label}`}>
            <span className="name">{r.name}</span>
            <div className="track"><div className="fill" style={{ width: `${(r.value / max) * 100}%` }} /></div>
            <span className="val">{r.label}</span>
          </div>
        ))}
      </div>
    );
  }
}

interface DashboardProps {}

interface DashboardState {
  data: DashboardData | null;
  error: string;
}

class DashboardPage extends React.Component<DashboardProps, DashboardState> {
  public state: DashboardState = { data: null, error: '' };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    api
      .get<DashboardData>('/admin/dashboard/')
      .then((r) => {
        if (this.mounted) this.setState({ data: r.data });
      })
      .catch((err) => {
        // e.g. a staff user not yet assigned to any place gets 403 with an explanation
        if (this.mounted) this.setState({ error: errorMessage(err) });
      });
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public render(): React.ReactNode {
    const { data, error } = this.state;
    if (error) {
      return (
        <div className="alert alert-warning d-flex align-items-center gap-2" role="alert">
          <i className="bi bi-exclamation-triangle-fill" aria-hidden="true" />
          <span>{error}</span>
        </div>
      );
    }
    if (!data) return <Loader />;
    const t = data.totals;
    const sc = data.status_counts;

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Dashboard</h1>
          <Link to="/admin/checkin" className="btn btn-accent">
            <i className="bi bi-upc-scan me-1" aria-hidden="true" /> Open gate check-in
          </Link>
        </div>

        <div className="row g-3 mb-3">
          <div className="col-sm-6 col-xl-3">
            <Stat label="Revenue (paid)" value={formatINR(t.revenue)} sub={`${formatNumber(t.bookings)} paid bookings`} icon="bi-currency-rupee" />
          </div>
          <div className="col-sm-6 col-xl-3">
            <Stat label="Tickets sold" value={formatNumber(t.visitors)} sub="All visitors across bookings" icon="bi-ticket-perforated" />
          </div>
          <div className="col-sm-6 col-xl-3">
            <Stat label="Expected today" value={formatNumber(t.expected_today)} sub={`${formatNumber(t.checked_in_today)} checked in so far`} icon="bi-calendar-check" />
          </div>
          <div className="col-sm-6 col-xl-3">
            <Stat label="Active museums" value={formatNumber(t.museums)} sub={`${formatNumber(t.users)} registered users`} icon="bi-building" />
          </div>
        </div>

        <div className="row g-3 mb-4">
          {(['online', 'counter'] as const).map((ch) => {
            const c = data.by_channel[ch] ?? { bookings: 0, revenue: 0, visitors: 0 };
            return (
              <div className="col-sm-6 col-xl-3" key={ch}>
                <Stat
                  label={ch === 'online' ? 'Online bookings' : 'Ticket counter sales'}
                  value={formatINR(c.revenue)}
                  sub={`${formatNumber(c.bookings)} bookings · ${formatNumber(c.visitors)} visitors`}
                  icon={ch === 'online' ? 'bi-globe' : 'bi-cash-coin'}
                />
              </div>
            );
          })}
          <div className="col-sm-6 col-xl-3">
            <Stat
              label="Group bookings"
              value={formatNumber(t.group_bookings ?? 0)}
              sub={`${formatNumber(t.group_visitors ?? 0)} visitors in groups`}
              icon="bi-people-fill"
            />
          </div>
        </div>

        <div className="card border-0 shadow-sm mb-4">
          <div className="card-body">
            <div className="d-flex justify-content-between align-items-center flex-wrap gap-2">
              <h2 className="h4 mb-0">Revenue, last 14 days</h2>
              <span className="text-muted small">By booking date</span>
            </div>
            <DailyChart data={data.daily} />
          </div>
        </div>

        <div className="row g-4 mb-4">
          <div className="col-lg-6">
            <div className="card border-0 shadow-sm h-100">
              <div className="card-body">
                <h2 className="h4">Top museums by revenue</h2>
                <RankList rows={data.top_museums.map((m) => ({ name: m.name, value: Number(m.revenue), label: formatINR(m.revenue) }))} />
              </div>
            </div>
          </div>
          <div className="col-lg-6">
            <div className="card border-0 shadow-sm h-100">
              <div className="card-body">
                <h2 className="h4">Visitors by state</h2>
                <RankList rows={data.by_state.map((s) => ({ name: s.state, value: s.visitors, label: formatNumber(s.visitors) }))} />
              </div>
            </div>
          </div>
        </div>

        <div className="card border-0 shadow-sm">
          <div className="card-header bg-white d-flex justify-content-between align-items-center flex-wrap gap-2 py-3">
            <h2 className="h4 mb-0">Recent bookings</h2>
            <div className="d-flex flex-wrap gap-1">
              <span className="badge bg-primary">{sc.confirmed ?? 0} confirmed</span>
              <span className="badge bg-success">{sc.checked_in ?? 0} checked in</span>
              <span className="badge bg-warning">{sc.pending ?? 0} pending</span>
              <span className="badge bg-secondary">{(sc.cancelled ?? 0) + (sc.expired ?? 0)} cancelled/expired</span>
            </div>
          </div>
          <div className="table-responsive">
            <table className="table table-hover align-middle mb-0">
              <thead className="table-light">
                <tr><th>Reference</th><th>Museum</th><th>Visit</th><th className="text-end">Visitors</th><th className="text-end">Amount</th><th>Status</th></tr>
              </thead>
              <tbody>
                {data.recent.map((b) => (
                  <tr key={b.reference}>
                    <td className="ref">{b.reference}</td>
                    <td>{b.museum_name}</td>
                    <td>{formatDate(b.visit_date)} · {formatTime(b.slot_start)}</td>
                    <td className="text-end">{b.total_visitors}</td>
                    <td className="text-end">{formatINR(b.total_amount)}</td>
                    <td><StatusBadge status={b.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }
}

export default DashboardPage;
