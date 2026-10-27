import * as React from 'react';
import { errorMessage, api } from '../../api/client';
import type { ExportJob } from '../../api/exports';
import { ReportDay, ReportSplit, ReportSummary } from '../../api/reports';
import { Loader } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { formatDate, formatINR, formatNumber, isoDate } from '../../utils/format';
import { DayTick, tickEvery } from '../../components/DayTick';
import { ExportMenu, ExportToast } from './Exports';

interface TileProps {
  label: string;
  value: string;
  sub?: string;
  icon: string;
}

class Tile extends React.Component<TileProps> {
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

interface RevenueChartProps {
  data: ReportDay[];
}

/** Single-series daily revenue columns (same markup as the dashboard chart). */
class RevenueChart extends React.Component<RevenueChartProps> {
  public render(): React.ReactNode {
    const { data } = this.props;
    const max = Math.max(1, ...data.map((d) => Number(d.revenue)));
    const every = tickEvery(data.length);
    return (
      <div className="chart-bars" role="img" aria-label={`Revenue per day, ${data.length} days`}>
        {data.map((d, i) => (
          <div className="col-bar" key={d.date} tabIndex={0}>
            <span className="tip">
              {formatDate(d.date, { day: 'numeric', month: 'short' })}: {formatINR(d.revenue)} · {d.bookings} booking{d.bookings === 1 ? '' : 's'}
            </span>
            <div className="bar" style={{ height: `${(Number(d.revenue) / max) * 100}%` }} />
            <DayTick dates={data.map((x) => x.date)} index={i} every={every} />
          </div>
        ))}
      </div>
    );
  }
}

interface SplitTableProps {
  title: string;
  rows: ReportSplit[];
}

class SplitTable extends React.Component<SplitTableProps> {
  public render(): React.ReactNode {
    const { title, rows } = this.props;
    const total = rows.reduce((n, r) => n + Number(r.revenue), 0);
    return (
      <div className="card border-0 shadow-sm h-100">
        <div className="card-body">
          <h2 className="h5">{title}</h2>
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead className="table-light">
                <tr><th scope="col">Type</th><th scope="col" className="text-end">Bookings</th><th scope="col" className="text-end">Visitors</th><th scope="col" className="text-end">Revenue</th><th scope="col" className="text-end">Share</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={String(r.key)}>
                    <td>{r.label}</td>
                    <td className="text-end">{formatNumber(r.bookings)}</td>
                    <td className="text-end">{formatNumber(r.visitors)}</td>
                    <td className="text-end">{formatINR(r.revenue)}</td>
                    <td className="text-end text-muted">{total > 0 ? `${Math.round((Number(r.revenue) / total) * 100)}%` : '—'}</td>
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

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
];

interface ReportsProps {}

interface ReportsState {
  from: string;
  to: string;
  museum: string;
  data: ReportSummary | null;
  loading: boolean;
  error: string;
  started: ExportJob | null;
}

class ReportsPage extends React.Component<ReportsProps, ReportsState> {
  public state: ReportsState = {
    from: isoDate(-29),
    to: isoDate(0),
    museum: '',
    data: null,
    loading: true,
    error: '',
    started: null,
  };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_prevProps: ReportsProps, prev: ReportsState): void {
    const s = this.state;
    if (s.from !== prev.from || s.to !== prev.to || s.museum !== prev.museum) this.scheduleLoad();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(), 250);
  }

  private load(): void {
    const { from, to, museum } = this.state;
    if (!from || !to) return;
    const id = ++this.requestId;
    const alive = (): boolean => this.mounted && id === this.requestId;
    this.setState({ loading: true, error: '' });
    api
      .get<ReportSummary>('/admin/reports/summary/', { params: { from, to, museum: museum || undefined } })
      .then((r) => alive() && this.setState({ data: r.data, loading: false }))
      .catch((err) => alive() && this.setState({ data: null, loading: false, error: errorMessage(err) }));
  }

  private setRange = (days: number): void => {
    this.setState({ from: isoDate(-(days - 1)), to: isoDate(0) });
  };

  public render(): React.ReactNode {
    const { from, to, museum, data, loading, error, started } = this.state;
    const t = data?.totals;

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Reports</h1>
          <ExportMenu
            filters={{ from, to, museum: museum || undefined }}
            onStarted={(job) => this.setState({ started: job, error: '' })}
            onError={(message) => this.setState({ error: message })}
          />
        </div>

        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-3 align-items-start">
              <div className="col-sm-6 col-lg-3">
                <label htmlFor="rep-from" className="form-label">Booked from</label>
                <input id="rep-from" type="date" className="form-control" value={from} max={to} onChange={(e) => this.setState({ from: e.target.value })} />
              </div>
              <div className="col-sm-6 col-lg-3">
                <label htmlFor="rep-to" className="form-label">Booked to</label>
                <input id="rep-to" type="date" className="form-control" value={to} min={from} onChange={(e) => this.setState({ to: e.target.value })} />
                <div className="d-flex gap-2 mt-1">
                  {RANGES.map((r) => (
                    <button key={r.days} type="button" className="btn btn-link btn-sm p-0" onClick={() => this.setRange(r.days)}>Last {r.label}</button>
                  ))}
                </div>
              </div>
              <div className="col-lg-6">
                <MuseumPicker label="Place (leave empty for all your places)" value={museum} clearable onChange={(slug) => this.setState({ museum: slug })} />
              </div>
            </div>
            <p className="text-muted small mb-0">
              Dates are booking dates. Revenue counts paid bookings (confirmed or checked in); refunds come from cancelled bookings.
            </p>
          </div>
        </div>

        {error && <div className="alert alert-danger">{error}</div>}
        <ExportToast job={started} onClose={() => this.setState({ started: null })} />

        {loading && !data ? (
          <Loader />
        ) : data && t ? (
          <div style={{ opacity: loading ? 0.6 : 1 }}>
            <div className="row g-3 mb-4">
              <div className="col-sm-6 col-xl-3">
                <Tile label="Revenue (paid)" value={formatINR(t.revenue)} sub={`${formatINR(t.discounts)} group discounts given`} icon="bi-currency-rupee" />
              </div>
              <div className="col-sm-6 col-xl-3">
                <Tile label="Paid bookings" value={formatNumber(t.bookings)} sub={`${formatNumber(t.cancelled)} cancelled`} icon="bi-receipt" />
              </div>
              <div className="col-sm-6 col-xl-3">
                <Tile label="Visitors" value={formatNumber(t.visitors)} sub="On paid bookings" icon="bi-people-fill" />
              </div>
              <div className="col-sm-6 col-xl-3">
                <Tile label="Refunds" value={formatINR(t.refunds)} sub="Refunded on cancellations" icon="bi-arrow-counterclockwise" />
              </div>
            </div>

            <div className="card border-0 shadow-sm mb-4">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-center flex-wrap gap-2">
                  <h2 className="h4 mb-0">Daily revenue</h2>
                  <span className="text-muted small">
                    {formatDate(data.from)} – {formatDate(data.to)}{data.museum ? ` · ${data.museum.name}` : ''}
                  </span>
                </div>
                <RevenueChart data={data.daily} />
              </div>
            </div>

            <div className="row g-4 mb-4">
              <div className="col-lg-6"><SplitTable title="By channel" rows={data.by_channel} /></div>
              <div className="col-lg-6"><SplitTable title="Groups vs individuals" rows={data.by_type} /></div>
            </div>

            <div className="card border-0 shadow-sm mb-4">
              <div className="card-body">
                <h2 className="h5">By place</h2>
                {data.by_museum.length === 0 ? (
                  <p className="text-muted small mb-0">No paid bookings in this period.</p>
                ) : (
                  <div className="table-responsive">
                    <table className="table table-sm table-hover align-middle mb-0">
                      <thead className="table-light">
                        <tr><th scope="col">Place</th><th scope="col">City</th><th scope="col" className="text-end">Bookings</th><th scope="col" className="text-end">Visitors</th><th scope="col" className="text-end">Revenue</th></tr>
                      </thead>
                      <tbody>
                        {data.by_museum.map((m) => (
                          <tr key={m.slug}>
                            <td>{m.name}</td>
                            <td className="text-muted">{m.city}, {m.state}</td>
                            <td className="text-end">{formatNumber(m.bookings)}</td>
                            <td className="text-end">{formatNumber(m.visitors)}</td>
                            <td className="text-end">{formatINR(m.revenue)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>

            <div className="card border-0 shadow-sm">
              <div className="card-body">
                <h2 className="h5">Day by day</h2>
                <div className="table-responsive" style={{ maxHeight: 420, overflowY: 'auto' }}>
                  <table className="table table-sm align-middle mb-0">
                    <thead className="table-light">
                      <tr><th scope="col">Date</th><th scope="col" className="text-end">Bookings</th><th scope="col" className="text-end">Visitors</th><th scope="col" className="text-end">Revenue</th><th scope="col" className="text-end">Refunds</th></tr>
                    </thead>
                    <tbody>
                      {[...data.daily].reverse().map((d) => (
                        <tr key={d.date}>
                          <td>{formatDate(d.date)}</td>
                          <td className="text-end">{formatNumber(d.bookings)}</td>
                          <td className="text-end">{formatNumber(d.visitors)}</td>
                          <td className="text-end">{formatINR(d.revenue)}</td>
                          <td className="text-end">{Number(d.refunds) > 0 ? formatINR(d.refunds) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="fw-semibold">
                      <tr>
                        <td>Total</td>
                        <td className="text-end">{formatNumber(t.bookings)}</td>
                        <td className="text-end">{formatNumber(t.visitors)}</td>
                        <td className="text-end">{formatINR(t.revenue)}</td>
                        <td className="text-end">{formatINR(t.refunds)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
}

export default ReportsPage;
