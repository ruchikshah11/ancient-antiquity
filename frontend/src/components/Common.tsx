import * as React from 'react';
import { Navigate } from 'react-router-dom';
import type { BookingStatus } from '../api/types';
import { withAuth, WithAuthProps } from '../context/AuthContext';
import { withI18n, WithI18nProps } from '../i18n';
import { withRouter, WithRouterProps } from '../utils/withRouter';

class LoaderBase extends React.Component<WithI18nProps> {
  public render(): React.ReactNode {
    return (
      <div className="d-flex justify-content-center py-5">
        <div className="spinner-border text-primary" role="status">
          <span className="visually-hidden">{this.props.i18n.t('common.loading')}</span>
        </div>
      </div>
    );
  }
}

export const Loader = withI18n(LoaderBase);

interface EmptyProps {
  title: string;
  children?: React.ReactNode;
}

export class Empty extends React.Component<EmptyProps> {
  public render(): React.ReactNode {
    const { title, children } = this.props;
    return (
      <div className="text-center py-5 text-muted">
        <i className="bi bi-search d-block display-5 mb-3" style={{ opacity: 0.5 }} aria-hidden="true" />
        <h4 className="text-secondary">{title}</h4>
        {children}
      </div>
    );
  }
}

const STATUS_BG: Record<BookingStatus, string> = {
  pending: 'bg-warning',
  confirmed: 'bg-success',
  checked_in: 'bg-success',
  cancelled: 'bg-danger',
  expired: 'bg-danger',
};

interface StatusBadgeProps extends WithI18nProps {
  status: BookingStatus;
}

class StatusBadgeBase extends React.Component<StatusBadgeProps> {
  public render(): React.ReactNode {
    const { status, i18n } = this.props;
    return <span className={`badge ${STATUS_BG[status]}`}>{i18n.t(`common.status.${status}`)}</span>;
  }
}

export const StatusBadge = withI18n(StatusBadgeBase);

interface PaginationProps extends WithI18nProps {
  page: number;
  count: number;
  pageSize?: number;
  onChange: (p: number) => void;
}

/** Page numbers to show: first, last and a window around the current page, with null for "…" gaps. */
export function pageWindow(page: number, pages: number, around = 1): (number | null)[] {
  const keep = new Set([1, pages]);
  for (let p = page - around; p <= page + around; p++) if (p >= 1 && p <= pages) keep.add(p);
  // Near either end, show a few more so the row doesn't jump in length.
  if (page <= around + 2) for (let p = 2; p <= Math.min(pages, around * 2 + 3); p++) keep.add(p);
  if (page >= pages - around - 1) for (let p = Math.max(1, pages - around * 2 - 2); p < pages; p++) keep.add(p);
  const sorted = [...keep].sort((x, y) => x - y);
  const out: (number | null)[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push(p - sorted[i - 1] === 2 ? p - 1 : null); // fill a single hidden page
    out.push(p);
  });
  return out;
}

/** "Showing 13–24 of 265" plus numbered page buttons (fewer numbers on phones). */
class PaginationBase extends React.Component<PaginationProps> {
  private renderPages(pages: number, around: number, className: string): React.ReactNode {
    const { page, onChange } = this.props;
    const { t } = this.props.i18n;
    return pageWindow(page, pages, around).map((p, i) =>
      p === null ? (
        <li key={`gap-${i}`} className={`gap ${className}`} aria-hidden="true">…</li>
      ) : (
        <li key={p} className={className}>
          <button
            type="button"
            className={`pg-btn ${p === page ? 'active' : ''}`}
            aria-current={p === page ? 'page' : undefined}
            aria-label={t('common.pagination.goTo', { page: p })}
            onClick={() => p !== page && onChange(p)}
          >
            {p}
          </button>
        </li>
      ),
    );
  }

  public render(): React.ReactNode {
    const { page, count, pageSize = 12, onChange } = this.props;
    const { t } = this.props.i18n;
    const pages = Math.max(1, Math.ceil(count / pageSize));
    if (pages <= 1) return null;
    const from = (page - 1) * pageSize + 1;
    const to = Math.min(count, page * pageSize);
    return (
      <nav aria-label={t('common.pagination.label')} className="pager mt-4">
        <div className="pager-info">{t('common.pagination.showing', { from, to, count })}</div>
        <ul>
          <li>
            <button type="button" className="pg-btn pg-arrow" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label={t('common.pagination.previous')} title={t('common.pagination.previous')}>
              <i className="bi bi-chevron-left" aria-hidden="true" />
            </button>
          </li>
          {this.renderPages(pages, 1, 'd-none d-sm-block')}
          {this.renderPages(pages, 0, 'd-sm-none')}
          <li>
            <button type="button" className="pg-btn pg-arrow" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label={t('common.pagination.next')} title={t('common.pagination.next')}>
              <i className="bi bi-chevron-right" aria-hidden="true" />
            </button>
          </li>
        </ul>
      </nav>
    );
  }
}

export const Pagination = withI18n(PaginationBase);

interface RequireAuthProps extends WithAuthProps, WithRouterProps {
  children: React.ReactNode;
  panel?: boolean;
  admin?: boolean;
}

/** Require login; optionally require staff/admin panel access. */
class RequireAuthBase extends React.Component<RequireAuthProps> {
  public render(): React.ReactNode {
    const { children, panel = false, admin = false, auth, router } = this.props;
    const { user, loading } = auth;
    const { location } = router;
    if (loading) return <Loader />;
    if (!user) return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
    if (panel && !user.is_panel_user) return <Navigate to="/" replace />;
    if (admin && !user.is_admin_role) return <Navigate to="/admin" replace />;
    return <>{children}</>;
  }
}

export const RequireAuth = withRouter(withAuth(RequireAuthBase));
