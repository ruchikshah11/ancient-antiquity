import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import type { AdminReview, Paginated, ReviewPhoto, ReviewPhotoStatus } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import { Stars } from '../../components/Reviews';
import { formatDate } from '../../utils/format';

interface AdminReviewsProps {}

interface AdminReviewsState {
  data: Paginated<AdminReview> | null;
  page: number;
  search: string;
  rating: string;
  visibility: string;
  /** '' = all, 'true' = reviews with photos waiting for approval */
  pendingPhotos: string;
  error: string;
  reload: number;
}

class AdminReviewsPage extends React.Component<AdminReviewsProps, AdminReviewsState> {
  public state: AdminReviewsState = {
    data: null,
    page: 1,
    search: '',
    rating: '',
    visibility: '',
    pendingPhotos: '',
    error: '',
    reload: 0,
  };

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_prevProps: AdminReviewsProps, prevState: AdminReviewsState): void {
    const s = this.state;
    if (
      s.page !== prevState.page ||
      s.search !== prevState.search ||
      s.rating !== prevState.rating ||
      s.visibility !== prevState.visibility ||
      s.pendingPhotos !== prevState.pendingPhotos ||
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
      const { page, search, rating, visibility, pendingPhotos } = this.state;
      api
        .get<Paginated<AdminReview>>('/admin/reviews/', {
          params: { page, search: search || undefined, rating: rating || undefined, is_published: visibility || undefined, has_pending_photos: pendingPhotos || undefined },
        })
        .then((r) => {
          if (this.mounted) this.setState({ data: r.data });
        });
    }, 250);
  }

  private toggle = async (r: AdminReview): Promise<void> => {
    try {
      const { data: updated } = await api.patch<AdminReview>(`/admin/reviews/${r.id}/`, { is_published: !r.is_published });
      this.setState((s) => ({ data: s.data && { ...s.data, results: s.data.results.map((x) => (x.id === r.id ? updated : x)) } }));
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private remove = async (r: AdminReview): Promise<void> => {
    if (!confirm(`Delete this ${r.rating}-star review by ${r.user_email}? This cannot be undone.`)) return;
    await api.delete(`/admin/reviews/${r.id}/`);
    this.setState((s) => ({ reload: s.reload + 1 }));
  };

  private moderate = async (r: AdminReview, photo: ReviewPhoto, status: ReviewPhotoStatus): Promise<void> => {
    try {
      const { data: updated } = await api.patch<ReviewPhoto>(`/admin/reviews/${r.id}/photos/${photo.id}/`, { status });
      this.setState((s) => ({
        error: '',
        data: s.data && {
          ...s.data,
          results: s.data.results.map((x) =>
            x.id === r.id ? { ...x, photos: (x.photos ?? []).map((p) => (p.id === photo.id ? updated : p)) } : x,
          ),
        },
      }));
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private renderPhotos(r: AdminReview): React.ReactNode {
    const photos = r.photos ?? [];
    if (!photos.length) return null;
    const badge: Record<ReviewPhotoStatus, string> = { pending: 'bg-warning text-dark', approved: 'bg-success', rejected: 'bg-secondary' };
    return (
      <div className="d-flex flex-wrap gap-3 mt-3">
        {photos.map((p) => (
          <figure key={p.id} className="review-photo-admin mb-0">
            <a href={p.url} target="_blank" rel="noreferrer" title="Open full size">
              <img src={p.url} alt={`Visitor photo ${p.id}`} className={`rounded border ${p.status === 'rejected' ? 'opacity-50' : ''}`} loading="lazy" />
            </a>
            <figcaption className="d-flex align-items-center justify-content-between gap-1 mt-1">
              <span className={`badge ${badge[p.status]}`}>{p.status_label}</span>
              <span className="btn-group btn-group-sm">
                <button type="button" className="btn btn-outline-success" disabled={p.status === 'approved'} onClick={() => this.moderate(r, p, 'approved')} title="Approve">
                  <i className="bi bi-check-lg" aria-hidden="true" /><span className="visually-hidden">Approve</span>
                </button>
                <button type="button" className="btn btn-outline-danger" disabled={p.status === 'rejected'} onClick={() => this.moderate(r, p, 'rejected')} title="Reject">
                  <i className="bi bi-x-lg" aria-hidden="true" /><span className="visually-hidden">Reject</span>
                </button>
              </span>
            </figcaption>
          </figure>
        ))}
      </div>
    );
  }

  private setPage = (page: number): void => {
    this.setState({ page });
  };

  public render(): React.ReactNode {
    const { data, page, search, rating, visibility, pendingPhotos, error } = this.state;

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
          <h1 className="h2 mb-0">Reviews</h1>
        </div>
        <p className="text-muted mb-4">
          Only visitors with a used or past ticket can post. Hide reviews that are abusive or off-topic. Hidden reviews don't count toward ratings. Visitor photos stay hidden until you approve them.
        </p>
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-lg-4">
                <input className="form-control" placeholder="Search text, museum, email…" value={search} onChange={(e) => this.setState({ search: e.target.value, page: 1 })} />
              </div>
              <div className="col-sm-4 col-lg-3">
                <select className="form-select" value={rating} onChange={(e) => this.setState({ rating: e.target.value, page: 1 })} aria-label="Rating">
                  <option value="">All ratings</option>
                  {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n === 5 ? '5 stars' : n === 1 ? '0.5–1.5 stars' : `${n}–${n}.5 stars`}</option>)}
                </select>
              </div>
              <div className="col-sm-4 col-lg-3">
                <select className="form-select" value={visibility} onChange={(e) => this.setState({ visibility: e.target.value, page: 1 })} aria-label="Visibility">
                  <option value="">Published + hidden</option>
                  <option value="true">Published</option>
                  <option value="false">Hidden</option>
                </select>
              </div>
              <div className="col-sm-4 col-lg-2">
                <select className="form-select" value={pendingPhotos} onChange={(e) => this.setState({ pendingPhotos: e.target.value, page: 1 })} aria-label="Photos">
                  <option value="">All reviews</option>
                  <option value="true">Has pending photos</option>
                </select>
              </div>
            </div>
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}

        {data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title="No reviews yet">Reviews appear here once visitors rate their visit.</Empty>
        ) : (
          <>
            <div className="d-flex flex-column gap-3">
              {data.results.map((r) => (
                <div key={r.id} className="card border-0 shadow-sm" style={{ opacity: r.is_published ? 1 : 0.65 }}>
                  <div className="card-body">
                    <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                      <div>
                        <Link to={`/museums/${r.museum_slug}#reviews`} target="_blank" className="text-decoration-none"><strong>{r.museum_name}</strong></Link>
                        <div className="text-muted small">{r.user_email} · {formatDate(r.created_at)}</div>
                      </div>
                      <div className="d-flex align-items-center flex-wrap gap-2">
                        {!r.is_published && <span className="badge bg-secondary">Hidden</span>}
                        <button className="btn btn-outline-primary btn-sm" onClick={() => this.toggle(r)}>
                          <i className={`bi ${r.is_published ? 'bi-eye-slash' : 'bi-eye'} me-1`} aria-hidden="true" />
                          {r.is_published ? 'Hide' : 'Publish'}
                        </button>
                        <button className="btn btn-outline-danger btn-sm" onClick={() => this.remove(r)}>
                          <i className="bi bi-trash me-1" aria-hidden="true" />Delete
                        </button>
                      </div>
                    </div>
                    <div className="d-flex align-items-center gap-2"><Stars value={r.rating} /><span className="small fw-semibold">{r.rating}</span></div>
                    {r.title && <div className="fw-semibold">{r.title}</div>}
                    {r.comment && <p className="mt-1 mb-0">{r.comment}</p>}
                    {this.renderPhotos(r)}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-3">
              <Pagination page={page} count={data.count} onChange={this.setPage} />
            </div>
          </>
        )}
      </div>
    );
  }
}

export default AdminReviewsPage;
