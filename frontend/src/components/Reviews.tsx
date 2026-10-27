import * as React from 'react';
import { api, errorMessage } from '../api/client';
import type { Review, ReviewHelpfulVote, ReviewPhoto, ReviewSummary } from '../api/types';
import { withAuth, WithAuthProps } from '../context/AuthContext';
import { withI18n, WithI18nProps } from '../i18n';
import { formatDate } from '../utils/format';
import { withRouter, WithRouterProps } from '../utils/withRouter';
import AuthModal from './AuthModal';

interface StarsProps extends WithI18nProps {
  value: number;
  size?: number;
}

/** Rounds to the nearest half star (4.3 -> 4.5, 4.2 -> 4). */
const toHalf = (v: number): number => Math.round(v * 2) / 2;
/** "4.5" or "4", never "4.0". */
const formatStars = (v: number): string => (v % 1 ? v.toFixed(1) : String(v));

/** Read-only stars with half-star precision. */
class StarsBase extends React.Component<StarsProps> {
  public render(): React.ReactNode {
    const { value, size } = this.props;
    const v = toHalf(value);
    return (
      <span className="stars" style={size ? { fontSize: size } : undefined} role="img" aria-label={this.props.i18n.t('common.reviews.outOf5', { n: formatStars(v) })}>
        {[1, 2, 3, 4, 5].map((n) => (
          <span key={n} className={v >= n ? '' : v >= n - 0.5 ? 'half' : 'off'} aria-hidden="true">★</span>
        ))}
      </span>
    );
  }
}

export const Stars = withI18n(StarsBase);

interface StarInputProps extends WithI18nProps {
  value: number;
  onChange: (n: number) => void;
}

interface StarInputState {
  hover: number;
}

/**
 * Rating picker in half stars: the left half of a star gives n - 0.5, the right half n.
 * Keyboard: a slider (arrow keys move half a star, Home/End jump to 0.5/5).
 */
class StarInputBase extends React.Component<StarInputProps, StarInputState> {
  public state: StarInputState = { hover: 0 };

  private pick(e: React.MouseEvent<HTMLButtonElement>, n: number): number {
    const r = e.currentTarget.getBoundingClientRect();
    return e.clientX - r.left < r.width / 2 ? n - 0.5 : n;
  }

  private onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    const { value, onChange } = this.props;
    const keys: Record<string, number> = { ArrowRight: 0.5, ArrowUp: 0.5, ArrowLeft: -0.5, ArrowDown: -0.5 };
    let next: number | null = null;
    if (e.key in keys) next = Math.min(5, Math.max(0.5, (value || 0) + keys[e.key]));
    if (e.key === 'Home') next = 0.5;
    if (e.key === 'End') next = 5;
    if (next !== null) {
      e.preventDefault();
      onChange(next);
    }
  };

  private label(v: number): string {
    return v ? `${formatStars(v)} · ${this.props.i18n.t(`common.reviews.rating.${Math.max(1, Math.floor(v))}`)}` : '';
  }

  public render(): React.ReactNode {
    const { value, onChange } = this.props;
    const { t } = this.props.i18n;
    const { hover } = this.state;
    const shown = hover || value;
    return (
      <div className="d-flex align-items-center gap-2">
        <div
          className="star-input"
          role="slider"
          tabIndex={0}
          aria-label={t('common.reviews.yourRating')}
          aria-valuemin={0.5}
          aria-valuemax={5}
          aria-valuenow={value || undefined}
          aria-valuetext={value ? this.label(value) : undefined}
          onKeyDown={this.onKeyDown}
          onMouseLeave={() => this.setState({ hover: 0 })}
        >
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              type="button"
              key={n}
              tabIndex={-1}
              aria-hidden="true"
              className={shown >= n ? 'on' : shown >= n - 0.5 ? 'half' : ''}
              onMouseMove={(e) => {
                const h = this.pick(e, n);
                if (h !== this.state.hover) this.setState({ hover: h });
              }}
              onClick={(e) => onChange(this.pick(e, n))}
            >
              ★
            </button>
          ))}
        </div>
        <span className="small text-muted star-label">{this.label(shown)}</span>
      </div>
    );
  }
}

const StarInput = withI18n(StarInputBase);

/** Review photos: JPG, PNG or WebP, up to 5 MB each and 4 per review (the server checks again). */
const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const PHOTO_MAX_MB = 5;
const PHOTO_MAX = 4;

interface NewPhoto {
  file: File;
  preview: string;
}

interface ReviewsProps extends WithAuthProps, WithRouterProps, WithI18nProps {
  slug: string;
  museumName: string;
}

interface ReviewsState {
  data: ReviewSummary | null;
  editing: boolean;
  rating: number;
  title: string;
  comment: string;
  error: string;
  busy: boolean;
  authOpen: boolean;
  /** Why the log-in modal is open: to write a review or to vote one helpful. */
  authFor: 'review' | 'vote';
  /** Reviews whose helpful vote is being sent (button disabled meanwhile). */
  voting: Record<number, boolean>;
  voteError: string;
  /** Photos picked in the form, uploaded after the review is saved. */
  newPhotos: NewPhoto[];
  photoError: string;
  /** Order of other visitors' reviews. */
  sort: 'newest' | 'oldest' | 'helpful';
  /** Only this star bar (1-5), or null for all. */
  stars: number | null;
  /** Other visitors' reviews loaded so far (first page, then "Show more"). */
  list: Review[];
  listTotal: number;
  nextOffset: number | null;
  loadingMore: boolean;
}

const FIRST_PAGE = 5;
const MORE_PAGE = 10;

class ReviewsBase extends React.Component<ReviewsProps, ReviewsState> {
  public state: ReviewsState = {
    data: null,
    editing: false,
    rating: 0,
    title: '',
    comment: '',
    error: '',
    busy: false,
    authOpen: false,
    authFor: 'review',
    voting: {},
    voteError: '',
    newPhotos: [],
    photoError: '',
    sort: 'newest',
    stars: null,
    list: [],
    listTotal: 0,
    nextOffset: null,
    loadingMore: false,
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentDidUpdate(prevProps: ReviewsProps, prevState: ReviewsState): void {
    if (prevProps.slug !== this.props.slug || prevProps.auth.user !== this.props.auth.user) this.load();

    // Arriving from "Rate your visit" (/museums/x#reviews): scroll here once content has loaded.
    const hash = this.props.router.location.hash;
    if (prevState.data !== this.state.data || prevProps.router.location.hash !== hash) {
      if (this.state.data && hash === '#reviews') document.getElementById('reviews')?.scrollIntoView({ behavior: 'smooth' });
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    this.state.newPhotos.forEach((p) => URL.revokeObjectURL(p.preview));
  }

  /** "Show more reviews": append the next page. */
  private loadMore = (): void => {
    const { sort, stars, nextOffset } = this.state;
    if (nextOffset === null) return;
    this.setState({ loadingMore: true });
    api.get<ReviewSummary>(`/museums/${this.props.slug}/reviews/`, {
      params: { sort, stars: stars ?? undefined, offset: nextOffset, limit: MORE_PAGE },
    }).then((r) => {
      if (!this.mounted) return;
      this.setState((st) => ({ list: [...st.list, ...r.data.results], nextOffset: r.data.next_offset ?? null, loadingMore: false }));
    }).catch(() => this.mounted && this.setState({ loadingMore: false }));
  };

  private filterStars = (n: number): void => {
    this.setState((st) => ({ stars: st.stars === n ? null : n }), this.load);
  };

  private load = (): void => {
    const { sort, stars } = this.state;
    api.get<ReviewSummary>(`/museums/${this.props.slug}/reviews/`, {
      params: { sort, stars: stars ?? undefined, limit: FIRST_PAGE },
    }).then((r) => {
      if (!this.mounted) return;
      const mine = r.data.my_review;
      this.setState({
        data: r.data,
        list: r.data.results,
        listTotal: r.data.results_total ?? r.data.results.length,
        nextOffset: r.data.next_offset ?? null,
        rating: mine?.rating ?? 0,
        title: mine?.title ?? '',
        comment: mine?.comment ?? '',
      });
    });
  };

  /** Photos of your review that still count toward the limit (approved or waiting). */
  private keptPhotos(): ReviewPhoto[] {
    return (this.state.data?.my_review?.photos ?? []).filter((p) => p.status !== 'rejected');
  }

  private photoLimit(): { max: number; maxMb: number } {
    const limits = this.state.data?.photo_limits;
    return { max: limits?.max_per_review ?? PHOTO_MAX, maxMb: limits?.max_mb ?? PHOTO_MAX_MB };
  }

  private addPhotos = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const { t } = this.props.i18n;
    const files = Array.from(e.target.files ?? []);
    e.target.value = ''; // picking the same file again still fires onChange
    const { max, maxMb } = this.photoLimit();
    const room = max - this.keptPhotos().length - this.state.newPhotos.length;
    const added: NewPhoto[] = [];
    let problem = '';
    for (const file of files) {
      if (!PHOTO_TYPES.includes(file.type)) problem = t('giving.photos.errType');
      else if (file.size > maxMb * 1024 * 1024) problem = t('giving.photos.errSize', { n: maxMb });
      else if (added.length >= room) problem = t('giving.photos.errCount', { n: max });
      else added.push({ file, preview: URL.createObjectURL(file) });
    }
    this.setState((s) => ({ newPhotos: [...s.newPhotos, ...added], photoError: problem }));
  };

  private removeNewPhoto = (index: number): void => {
    this.setState((s) => {
      const photo = s.newPhotos[index];
      if (photo) URL.revokeObjectURL(photo.preview);
      return { newPhotos: s.newPhotos.filter((_, i) => i !== index), photoError: '' };
    });
  };

  private deletePhoto = async (photo: ReviewPhoto): Promise<void> => {
    if (!confirm(this.props.i18n.t('giving.photos.confirmDelete'))) return;
    try {
      await api.delete(`/museums/${this.props.slug}/reviews/photos/${photo.id}/`);
      this.load();
    } catch (err) {
      this.setState({ photoError: errorMessage(err) });
    }
  };

  /** Uploads the picked photos; returns an error message, or '' when done. */
  private uploadPhotos = async (): Promise<string> => {
    const { newPhotos } = this.state;
    if (!newPhotos.length) return '';
    const form = new FormData();
    newPhotos.forEach((p) => form.append('file', p.file));
    try {
      await api.post(`/museums/${this.props.slug}/reviews/photos/`, form);
      newPhotos.forEach((p) => URL.revokeObjectURL(p.preview));
      if (this.mounted) this.setState({ newPhotos: [] });
      return '';
    } catch (err) {
      return this.props.i18n.t('giving.photos.uploadFailed', { error: errorMessage(err) });
    }
  };

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { rating, title, comment } = this.state;
    if (!rating) {
      this.setState({ error: this.props.i18n.t('common.reviews.chooseRating') });
      return;
    }
    this.setState({ busy: true, error: '', photoError: '' });
    try {
      await api.post(`/museums/${this.props.slug}/reviews/`, { rating, title, comment });
      // The review is saved; photos go up afterwards (a photo problem keeps the form open to retry).
      const photoError = await this.uploadPhotos();
      if (!this.mounted) return;
      this.setState({ editing: !!photoError, photoError });
      this.load();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busy: false });
    }
  };

  private remove = async (): Promise<void> => {
    if (!confirm(this.props.i18n.t('common.reviews.confirmDelete'))) return;
    await api.delete(`/museums/${this.props.slug}/reviews/`);
    this.setState({ editing: false });
    this.load();
  };

  /** Photos under a review; your own pending ones are marked "Waiting for approval". */
  private renderReviewPhotos(review: Review, own = false): React.ReactNode {
    const { t } = this.props.i18n;
    const photos = (review.photos ?? []).filter((p) => p.status !== 'rejected');
    if (!photos.length) return null;
    return (
      <div className="review-photos d-flex flex-wrap gap-2 mt-2">
        {photos.map((p) => (
          <div key={p.id} className="review-photo position-relative">
            <a href={p.url} target="_blank" rel="noreferrer">
              <img src={p.url} alt={t('giving.photos.alt', { name: review.user_name })} loading="lazy" className={`rounded ${p.status === 'pending' ? 'is-pending' : ''}`} />
            </a>
            {p.status === 'pending' && (
              <span className="badge bg-warning text-dark review-photo-badge">
                <i className="bi bi-hourglass-split me-1" aria-hidden="true" />
                {t('giving.photos.pending')}
              </span>
            )}
            {own && (
              <button type="button" className="btn btn-sm btn-light review-photo-remove" onClick={() => this.deletePhoto(p)} aria-label={t('giving.photos.remove')} title={t('giving.photos.remove')}>
                <i className="bi bi-x-lg" aria-hidden="true" />
              </button>
            )}
          </div>
        ))}
      </div>
    );
  }

  private renderPhotoPicker(): React.ReactNode {
    const { t } = this.props.i18n;
    const { newPhotos, photoError, data } = this.state;
    const { max, maxMb } = this.photoLimit();
    const room = max - this.keptPhotos().length - newPhotos.length;
    return (
      <div className="mb-3">
        <span className="form-label d-block mb-0">{t('giving.photos.add')}</span>
        {data?.my_review && this.renderReviewPhotos(data.my_review, true)}
        {newPhotos.length > 0 && (
          <div className="review-photos d-flex flex-wrap gap-2 mt-2">
            {newPhotos.map((p, i) => (
              <div key={p.preview} className="review-photo position-relative">
                <img src={p.preview} alt={p.file.name} className="rounded" />
                <button type="button" className="btn btn-sm btn-light review-photo-remove" onClick={() => this.removeNewPhoto(i)} aria-label={t('giving.photos.removeNamed', { name: p.file.name })} title={t('giving.photos.remove')}>
                  <i className="bi bi-x-lg" aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        )}
        {room > 0 && (
          <label className="btn btn-outline-primary btn-sm mt-2">
            <i className="bi bi-camera me-1" aria-hidden="true" />
            {t('giving.photos.choose')}
            <input type="file" accept={PHOTO_TYPES.join(',')} multiple className="visually-hidden" onChange={this.addPhotos} />
          </label>
        )}
        <div className="form-text">{t('giving.photos.help', { n: max, mb: maxMb })}</div>
        {photoError && <div className="text-danger small mt-1" role="alert">{photoError}</div>}
      </div>
    );
  }

  private renderVisitorPhotos(): React.ReactNode {
    const { t } = this.props.i18n;
    const photos = this.state.data?.visitor_photos ?? [];
    if (!photos.length) return null;
    return (
      <div className="visitor-photos mt-3">
        <h4 className="h6 mb-2"><i className="bi bi-images me-1 text-primary" aria-hidden="true" />{t('giving.photos.strip')}</h4>
        <div className="visitor-photo-strip d-flex gap-2 pb-2">
          {photos.map((p) => (
            <a key={p.id} href={p.url} target="_blank" rel="noreferrer" className="flex-shrink-0" title={t('giving.photos.by', { name: p.user_name })}>
              <img src={p.url} alt={t('giving.photos.alt', { name: p.user_name })} loading="lazy" className="rounded" />
            </a>
          ))}
        </div>
      </div>
    );
  }

  private setRating = (rating: number): void => {
    this.setState({ rating });
  };

  /** "Helpful" toggle: logged-out visitors get the log-in modal; otherwise POST (vote) or DELETE (undo). */
  private toggleHelpful = async (review: Review): Promise<void> => {
    if (!this.props.auth.user) {
      this.setState({ authOpen: true, authFor: 'vote' });
      return;
    }
    if (this.state.voting[review.id]) return;
    this.setState((s) => ({ voting: { ...s.voting, [review.id]: true }, voteError: '' }));
    const url = `/museums/${this.props.slug}/reviews/${review.id}/helpful/`;
    try {
      const { data } = review.voted_by_me ? await api.delete<ReviewHelpfulVote>(url) : await api.post<ReviewHelpfulVote>(url);
      if (!this.mounted) return;
      this.setState((s) => ({
        list: s.list.map((r) => (r.id === data.id ? { ...r, helpful_count: data.helpful_count, voted_by_me: data.voted_by_me } : r)),
      }));
    } catch (err) {
      if (this.mounted) this.setState({ voteError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState((s) => ({ voting: { ...s.voting, [review.id]: false } }));
    }
  };

  private closeAuth = (): void => {
    this.setState({ authOpen: false });
  };

  public render(): React.ReactNode {
    const { museumName } = this.props;
    const { t } = this.props.i18n;
    const { user } = this.props.auth;
    const { data, editing, rating, title, comment, error, busy, authOpen } = this.state;

    if (!data) return null;
    const mine = data.my_review;
    const others = this.state.list.filter((r) => r.id !== mine?.id);
    const { stars, listTotal, nextOffset, loadingMore } = this.state;
    const showForm = data.can_review && (editing || !mine);

    return (
      <section id="reviews" className="mt-5">
        <h3 className="mb-3">{t('common.reviews.title')}</h3>

        {data.count > 0 ? (
          <div className="card border-0 shadow-sm">
            <div className="card-body">
              <div className="row g-4 align-items-center">
                <div className="col-sm-4 text-center">
                  <div className="display-5 fw-bold text-primary lh-1 mb-1">{data.average?.toFixed(1)}</div>
                  <Stars value={data.average ?? 0} size={18} />
                  <div className="small text-muted">{t(data.count > 1 ? 'common.reviews.count.other' : 'common.reviews.count.one', { n: data.count })}</div>
                </div>
                <div className="col-sm-8">
                  {(['5', '4', '3', '2', '1'] as const).map((n) => {
                    const c = data.breakdown[n];
                    const pct = data.count ? (c / data.count) * 100 : 0;
                    return (
                      <button
                        type="button"
                        className={`review-bar d-flex align-items-center gap-2 small py-1 w-100 ${stars === Number(n) ? 'active' : ''}`}
                        key={n}
                        disabled={!c}
                        aria-pressed={stars === Number(n)}
                        onClick={() => this.filterStars(Number(n))}
                      >
                        <span className="text-nowrap" style={{ width: 48 }}>{t('common.reviews.nStar', { n })}</span>
                        <div className="progress flex-grow-1" style={{ height: 8 }}>
                          <div
                            className="progress-bar bg-warning"
                            role="progressbar"
                            style={{ width: `${pct}%` }}
                            aria-valuenow={c}
                            aria-valuemin={0}
                            aria-valuemax={data.count}
                            aria-label={t('common.reviews.nStar', { n })}
                          />
                        </div>
                        <span className="fw-semibold text-end" style={{ width: 28 }}>{c}</span>
                      </button>
                    );
                  })}
                  <div className="small text-muted mt-1 ps-2">
                    <i className="bi bi-hand-index me-1" aria-hidden="true" />{t('common.reviews.barHint')}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-muted">{t('common.reviews.none', { name: museumName })}</p>
        )}

        {this.renderVisitorPhotos()}

        {/* Your review / call to action */}
        <div className="mt-3">
          {!user ? (
            <div className="card border-0 shadow-sm">
              <div className="card-body d-flex justify-content-between align-items-center gap-2 flex-wrap">
                <span className="text-muted">{t('common.reviews.loginPrompt')}</span>
                <button type="button" className="btn btn-outline-primary btn-sm" onClick={() => this.setState({ authOpen: true, authFor: 'review' })}>
                  <i className="bi bi-pencil-square me-1" aria-hidden="true" />
                  {t('common.reviews.write')}
                </button>
              </div>
            </div>
          ) : showForm ? (
            <form className="card border-0 shadow-sm" onSubmit={this.submit}>
              <div className="card-body">
                <h4 className="h5 mb-3">{mine ? t('common.reviews.editYours') : t('common.reviews.rateVisit')}</h4>
                {error && <div className="alert alert-danger">{error}</div>}
                <div className="mb-3">
                  <StarInput value={rating} onChange={this.setRating} />
                </div>
                <div className="mb-3">
                  <label htmlFor="rv-title" className="form-label">{t('common.reviews.headline')}</label>
                  <input id="rv-title" className="form-control" maxLength={120} value={title} onChange={(e) => this.setState({ title: e.target.value })} placeholder={t('common.reviews.headlinePlaceholder')} />
                </div>
                <div className="mb-3">
                  <label htmlFor="rv-comment" className="form-label">{t('common.reviews.yourReview')}</label>
                  <textarea id="rv-comment" className="form-control" rows={4} maxLength={2000} value={comment} onChange={(e) => this.setState({ comment: e.target.value })} placeholder={t('common.reviews.commentPlaceholder')} />
                </div>
                {this.renderPhotoPicker()}
                <div className="d-flex gap-2 flex-wrap">
                  <button className="btn btn-accent" disabled={busy}>{busy ? t('common.reviews.saving') : mine ? t('common.reviews.update') : t('common.reviews.post')}</button>
                  {mine && <button type="button" className="btn btn-light" onClick={() => this.setState({ editing: false })}>{t('common.cancel')}</button>}
                </div>
              </div>
            </form>
          ) : mine ? (
            <div className="card border-0 shadow-sm">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-center gap-2 flex-wrap">
                  <strong>{t('common.reviews.yourReview')}</strong>
                  <div className="d-flex gap-1">
                    <button type="button" className="btn btn-light btn-sm" onClick={() => this.setState({ editing: true })}>
                      <i className="bi bi-pencil me-1" aria-hidden="true" />
                      {t('common.edit')}
                    </button>
                    <button type="button" className="btn btn-light btn-sm text-danger" onClick={this.remove}>
                      <i className="bi bi-trash me-1" aria-hidden="true" />
                      {t('common.delete')}
                    </button>
                  </div>
                </div>
                <Stars value={mine.rating} />
                {mine.title && <div className="fw-semibold">{mine.title}</div>}
                {mine.comment && <p className="mt-1 mb-0">{mine.comment}</p>}
                {this.renderReviewPhotos(mine, true)}
                {this.keptPhotos().length < this.photoLimit().max && (
                  <button type="button" className="btn btn-link btn-sm px-0 mt-1" onClick={() => this.setState({ editing: true })}>
                    <i className="bi bi-camera me-1" aria-hidden="true" />
                    {t('giving.photos.addToReview')}
                  </button>
                )}
              </div>
            </div>
          ) : (
            <p className="small text-muted">{t('common.reviews.afterVisit', { name: museumName })}</p>
          )}
        </div>

        <div className="mt-2">
          {(others.length > 1 || stars) && (
            <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
              <span className="small text-muted">
                {stars ? (
                  <>
                    {t('common.reviews.filtered', { n: stars, count: listTotal })}{' '}
                    <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => this.filterStars(stars)}>
                      {t('common.reviews.showAll')}
                    </button>
                  </>
                ) : null}
              </span>
              <span className="d-flex align-items-center gap-2">
              <label htmlFor="review-sort" className="small text-muted mb-0">{t('common.reviews.sort')}</label>
              <select
                id="review-sort"
                className="form-select form-select-sm w-auto"
                value={this.state.sort}
                onChange={(e) => this.setState({ sort: e.target.value as ReviewsState['sort'] }, this.load)}
              >
                <option value="newest">{t('common.reviews.sort.newest')}</option>
                <option value="oldest">{t('common.reviews.sort.oldest')}</option>
                <option value="helpful">{t('common.reviews.sort.helpful')}</option>
              </select>
              </span>
            </div>
          )}
          {others.map((r) => (
            <article key={r.id} className="border-top py-3">
              <div className="d-flex justify-content-between align-items-center gap-2 flex-wrap">
                <div className="d-flex align-items-center gap-2 flex-wrap">
                  <strong>{r.user_name}</strong>
                  <span className="text-success small fw-semibold">
                    <i className="bi bi-patch-check-fill me-1" aria-hidden="true" />
                    {t('common.reviews.verified')}
                  </span>
                </div>
                <span className="small text-muted">{formatDate(r.created_at)}</span>
              </div>
              <Stars value={r.rating} />
              {r.title && <div className="fw-semibold mt-1">{r.title}</div>}
              {r.comment && <p className="text-secondary mt-1 mb-0">{r.comment}</p>}
              {this.renderReviewPhotos(r)}
              <div className="mt-2">
                <button
                  type="button"
                  className={`btn btn-sm ${r.voted_by_me ? 'btn-primary' : 'btn-outline-secondary'}`}
                  aria-pressed={!!r.voted_by_me}
                  disabled={!!this.state.voting[r.id]}
                  title={t(r.voted_by_me ? 'common.reviews.helpfulUndo' : 'common.reviews.helpfulMark')}
                  onClick={() => this.toggleHelpful(r)}
                >
                  <span aria-hidden="true" className="me-1">👍</span>
                  {t('common.reviews.helpful', { n: r.helpful_count ?? 0 })}
                </button>
              </div>
            </article>
          ))}
          {nextOffset !== null && (
            <div className="text-center border-top pt-3">
              <button type="button" className="btn btn-outline-primary" disabled={loadingMore} onClick={this.loadMore}>
                {loadingMore ? <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" /> : <i className="bi bi-chevron-down me-1" aria-hidden="true" />}
                {t('common.reviews.showMore', { n: listTotal - others.length })}
              </button>
            </div>
          )}
        </div>

        {this.state.voteError && <div className="alert alert-danger py-2 small mt-2" role="alert">{this.state.voteError}</div>}

        <AuthModal
          open={authOpen}
          title={t(this.state.authFor === 'vote' ? 'common.reviews.helpfulAuthTitle' : 'common.reviews.authTitle')}
          reason={t(this.state.authFor === 'vote' ? 'common.reviews.helpfulAuthReason' : 'common.reviews.authReason')}
          initialTab="login"
          onClose={this.closeAuth}
          onDone={this.closeAuth}
        />
      </section>
    );
  }
}

export default withRouter(withAuth(withI18n(ReviewsBase)));
