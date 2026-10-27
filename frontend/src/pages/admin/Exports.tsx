import * as React from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../api/client';
import {
  deleteExport, downloadExport, EXPORTS_PAGE, ExportFilters, ExportJob, ExportKind, formatBytes, isActive,
  listExports, startExport,
} from '../../api/exports';
import { Empty, Loader } from '../../components/Common';
import { formatDateTime, formatNumber } from '../../utils/format';

const POLL_MS = 3000;

const FILTER_LABELS: Record<string, string> = {
  from: 'Booked from', to: 'Booked to', museum: 'Place', search: 'Search', status: 'Status', channel: 'Channel',
  is_group: 'Groups', visit_date: 'Visit date', role: 'Role', is_active: 'Active', is_sample: 'Sample',
};

const STATUS_CLASS: Record<string, string> = {
  pending: 'bg-secondary', running: 'bg-info text-dark', done: 'bg-success', failed: 'bg-danger', expired: 'bg-light text-dark',
};

function describeFilters(filters: Record<string, string>): string {
  const parts = Object.entries(filters).map(([k, v]) => `${FILTER_LABELS[k] ?? k}: ${v}`);
  return parts.length ? parts.join(' · ') : 'Everything you can access';
}

/* ------------------------------------------------------------------ shared: "Export…" menu + toast */

interface ExportOption {
  kind: ExportKind;
  label: string;
  icon: string;
}

export const BOOKING_EXPORTS: ExportOption[] = [
  { kind: 'bookings_xlsx', label: 'Excel (.xlsx)', icon: 'bi-file-earmark-excel' },
  { kind: 'bookings_csv', label: 'CSV (best for very large exports)', icon: 'bi-file-earmark-text' },
  { kind: 'bookings_pdf', label: 'PDF (first 5,000 rows)', icon: 'bi-file-earmark-pdf' },
];

interface ExportMenuProps {
  filters: ExportFilters;
  options?: ExportOption[];
  className?: string;
  onStarted: (job: ExportJob) => void;
  onError: (message: string) => void;
}

interface ExportMenuState {
  open: boolean;
  busy: boolean;
}

/** "Export…" button: starts a background export job for the current filters. */
export class ExportMenu extends React.Component<ExportMenuProps, ExportMenuState> {
  public state: ExportMenuState = { open: false, busy: false };

  private root = React.createRef<HTMLDivElement>();

  public componentDidMount(): void {
    document.addEventListener('mousedown', this.outside);
  }

  public componentWillUnmount(): void {
    document.removeEventListener('mousedown', this.outside);
  }

  private outside = (e: MouseEvent): void => {
    if (this.state.open && this.root.current && !this.root.current.contains(e.target as Node)) this.setState({ open: false });
  };

  private start = async (kind: ExportKind): Promise<void> => {
    this.setState({ open: false, busy: true });
    try {
      const job = await startExport(kind, this.props.filters);
      this.props.onStarted(job);
    } catch (err) {
      this.props.onError(errorMessage(err, 'The export could not be started.'));
    } finally {
      this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { options = BOOKING_EXPORTS, className = 'btn btn-accent' } = this.props;
    const { open, busy } = this.state;
    return (
      <div className="dropdown" ref={this.root}>
        <button type="button" className={`${className} dropdown-toggle`} aria-expanded={open} disabled={busy}
          onClick={() => this.setState((s) => ({ open: !s.open }))}>
          <i className="bi bi-cloud-download me-1" aria-hidden="true" />
          {busy ? 'Starting…' : 'Export…'}
        </button>
        <ul className={`dropdown-menu dropdown-menu-end${open ? ' show' : ''}`} style={open ? { right: 0 } : undefined}>
          {options.map((o) => (
            <li key={o.kind}>
              <button type="button" className="dropdown-item" onClick={() => this.start(o.kind)}>
                <i className={`bi ${o.icon} me-2`} aria-hidden="true" />{o.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }
}

interface ExportToastProps {
  job: ExportJob | null;
  onClose: () => void;
}

/** Bottom-right notice after an export was started, linking to the Exports page. */
export class ExportToast extends React.Component<ExportToastProps> {
  private timer: ReturnType<typeof setTimeout> | undefined;

  public componentDidUpdate(prev: ExportToastProps): void {
    if (this.props.job && this.props.job !== prev.job) {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.props.onClose(), 10000);
    }
  }

  public componentWillUnmount(): void {
    clearTimeout(this.timer);
  }

  public render(): React.ReactNode {
    const { job, onClose } = this.props;
    if (!job) return null;
    return (
      <div className="position-fixed bottom-0 end-0 p-3" style={{ zIndex: 1080 }}>
        <div className="toast show border-0 shadow" role="status" aria-live="polite">
          <div className="toast-header">
            <i className="bi bi-cloud-download text-accent me-2" aria-hidden="true" />
            <strong className="me-auto">Export started</strong>
            <button type="button" className="btn-close" aria-label="Close" onClick={onClose} />
          </div>
          <div className="toast-body">
            {job.kind_label} is being prepared in the background. You can keep working.
            <div className="mt-2">
              <Link to={EXPORTS_PAGE} className="btn btn-sm btn-primary" onClick={onClose}>Go to Exports</Link>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

/* ------------------------------------------------------------------ the Exports page */

interface ExportsState {
  jobs: ExportJob[] | null;
  keepDays: number;
  error: string;
  downloading: number | null;
}

class ExportsPage extends React.Component<Record<string, never>, ExportsState> {
  public state: ExportsState = { jobs: null, keepDays: 7, error: '', downloading: null };

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

  private load = (): void => {
    clearTimeout(this.timer);
    listExports()
      .then((data) => {
        if (!this.mounted) return;
        this.setState({ jobs: data.results, keepDays: data.keep_days, error: '' });
        // Live status: poll while anything is waiting or running.
        if (data.results.some(isActive)) this.timer = setTimeout(this.load, POLL_MS);
      })
      .catch((err) => {
        if (!this.mounted) return;
        this.setState((s) => ({ error: errorMessage(err), jobs: s.jobs ?? [] }));
        this.timer = setTimeout(this.load, POLL_MS * 3);
      });
  };

  private download = async (job: ExportJob): Promise<void> => {
    this.setState({ downloading: job.id, error: '' });
    try {
      await downloadExport(job);
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err, 'The file could not be downloaded.') });
    } finally {
      if (this.mounted) this.setState({ downloading: null });
    }
  };

  private remove = async (job: ExportJob): Promise<void> => {
    if (!confirm(`Delete ${job.kind_label} #${job.id}?`)) return;
    try {
      await deleteExport(job.id);
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private progress(job: ExportJob): React.ReactNode {
    if (job.status === 'running') {
      const pct = job.total_rows ? Math.min(100, Math.round((job.row_count / job.total_rows) * 100)) : 0;
      return (
        <>
          <div className="progress" style={{ height: 6, minWidth: 120 }} aria-label="Export progress">
            <div className="progress-bar progress-bar-striped progress-bar-animated" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-muted small">
            {formatNumber(job.row_count)}{job.total_rows !== null ? ` of ${formatNumber(job.total_rows)}` : ''} rows
          </div>
        </>
      );
    }
    if (job.status === 'done') return <>{formatNumber(job.row_count)} rows</>;
    return <span className="text-muted">—</span>;
  }

  public render(): React.ReactNode {
    const { jobs, keepDays, error, downloading } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
          <h1 className="h2 mb-0">Exports</h1>
          <button type="button" className="btn btn-light" onClick={this.load}>
            <i className="bi bi-arrow-clockwise me-1" aria-hidden="true" /> Refresh
          </button>
        </div>
        <p className="text-muted mb-4">
          Exports run in the background, so large ones (lakhs of bookings) don&apos;t block the page. Start one with
          &ldquo;Export…&rdquo; on Bookings or Reports. Files are kept for {keepDays} days and only you can download them.
        </p>
        {error && <div className="alert alert-danger">{error}</div>}
        {jobs === null ? (
          <Loader />
        ) : jobs.length === 0 ? (
          <Empty title="No exports yet" />
        ) : (
          <div className="card border-0 shadow-sm">
            <div className="table-responsive">
              <table className="table align-middle mb-0">
                <thead className="table-light">
                  <tr><th>Started</th><th>Export</th><th>Status</th><th>Rows</th><th className="text-end">Size</th><th /></tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id}>
                      <td className="small text-nowrap">{formatDateTime(job.created_at)}</td>
                      <td>
                        <div className="fw-semibold">{job.kind_label}</div>
                        <div className="text-muted small">{describeFilters(job.filters)}</div>
                        {job.note && <div className="small text-muted"><i className="bi bi-info-circle me-1" aria-hidden="true" />{job.note}</div>}
                        {job.error && <div className="small text-danger">{job.error}</div>}
                      </td>
                      <td><span className={`badge ${STATUS_CLASS[job.status] ?? 'bg-secondary'}`}>{job.status_label}</span></td>
                      <td className="small">{this.progress(job)}</td>
                      <td className="text-end small text-nowrap">{job.status === 'done' ? formatBytes(job.file_size) : '—'}</td>
                      <td className="text-end text-nowrap">
                        {job.download_url && (
                          <button type="button" className="btn btn-sm btn-primary me-1" disabled={downloading === job.id} onClick={() => this.download(job)}>
                            <i className="bi bi-download me-1" aria-hidden="true" />{downloading === job.id ? 'Downloading…' : 'Download'}
                          </button>
                        )}
                        {!isActive(job) && (
                          <button type="button" className="btn btn-sm btn-light" onClick={() => this.remove(job)} aria-label={`Delete export ${job.id}`} title="Delete">
                            <i className="bi bi-trash" aria-hidden="true" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  }
}

export default ExportsPage;
