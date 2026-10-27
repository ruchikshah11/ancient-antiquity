import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import { PASS_CATEGORIES } from '../../api/passes';
import type { ComboPass, PassOrder } from '../../api/passes';
import { Empty, Loader } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatDateTime, formatINR, museumGradient, sizedImage } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import FxHint from '../../components/FxHint';
import { loadSiteSettings } from '../../api/siteSettings';
import type { SiteSettings } from '../../api/siteSettings';

/** /passes: combo passes on sale, and (signed in) the visitor's own passes with QR and per-place status. */

type PassesProps = WithAuthProps & WithI18nProps & WithRouterProps;

interface PassesState {
  passes: ComboPass[] | null;
  error: string;
  orders: PassOrder[] | null;
  ordersError: string;
  busyRef: string;
  site: SiteSettings | null;
}

const ORDER_BADGE: Record<PassOrder['status'], string> = {
  pending: 'bg-warning',
  confirmed: 'bg-success',
  cancelled: 'bg-danger',
  expired: 'bg-secondary',
};

class Passes extends React.Component<PassesProps, PassesState> {
  public state: PassesState = { passes: null, error: '', orders: null, ordersError: '', busyRef: '', site: null };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    cachedGet<ComboPass[]>('/passes/', undefined, (data) => this.mounted && this.setState({ passes: data, error: '' })).catch(
      () => this.mounted && this.setState({ passes: [], error: this.props.i18n.t('passes.loadError') }),
    );
    this.loadOrders();
    loadSiteSettings((site) => this.mounted && this.setState({ site })).catch(() => undefined);
  }

  public componentDidUpdate(prevProps: PassesProps): void {
    if (prevProps.auth.user !== this.props.auth.user) this.loadOrders();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private loadOrders = async (): Promise<void> => {
    if (!this.props.auth.user) {
      this.setState({ orders: null });
      return;
    }
    try {
      const { data } = await api.get<PassOrder[]>('/pass-orders/');
      if (!this.mounted) return;
      this.setState({ orders: data, ordersError: '' }, this.scrollToMine);
    } catch (err) {
      if (this.mounted) this.setState({ orders: [], ordersError: errorMessage(err) });
    }
  };

  private scrollToMine = (): void => {
    if (this.props.router.location.hash === '#my-passes') document.getElementById('my-passes')?.scrollIntoView();
  };

  private cancel = async (order: PassOrder): Promise<void> => {
    const { t } = this.props.i18n;
    const refund = Number(order.refundable_amount);
    const question =
      order.status === 'pending'
        ? t('passes.mine.confirmCancelPending')
        : refund > 0
          ? t('passes.mine.confirmCancelRefund', { amount: formatINR(refund) })
          : t('passes.mine.confirmCancelNoRefund');
    if (!window.confirm(question)) return;
    this.setState({ busyRef: order.reference });
    try {
      const { data } = await api.post<PassOrder>(`/pass-orders/${order.reference}/cancel/`);
      if (this.mounted) this.setState((s) => ({ orders: (s.orders ?? []).map((o) => (o.reference === data.reference ? data : o)), ordersError: '' }));
    } catch (err) {
      if (this.mounted) this.setState({ ordersError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ busyRef: '' });
    }
  };

  private renderCard(p: ComboPass): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <div key={p.slug} className="col-md-6 col-lg-4">
        <div className="card h-100 border-0 shadow-sm">
          <div
            className="card-img-top position-relative"
            style={{
              height: 170,
              background: p.image_url ? `center / cover no-repeat url("${sizedImage(p.image_url, 500)}")` : museumGradient(p.slug),
            }}
            role="img"
            aria-label={p.name}
          >
            <span className="badge bg-accent position-absolute top-0 start-0 m-2">
              {p.validity_days > 1 ? t('passes.validDays', { n: p.validity_days }) : t('passes.validOneDay')}
            </span>
            {p.featured && (
              <span className="badge bg-light text-dark position-absolute top-0 end-0 m-2">
                <i className="bi bi-star-fill text-warning me-1" aria-hidden="true" />{t('passes.featured')}
              </span>
            )}
          </div>
          <div className="card-body d-flex flex-column">
            <h2 className="h5 card-title">{p.name}</h2>
            <div className="small text-muted mb-1">{t('passes.includes', { n: p.sites.length })}</div>
            <ul className="list-unstyled small mb-3">
              {p.sites.map((s) => (
                <li key={s.slug}>
                  <i className="bi bi-geo-alt text-primary me-1" aria-hidden="true" />
                  {s.name} <span className="text-muted">· {s.city_name}</span>
                </li>
              ))}
            </ul>
            <div className="mt-auto d-flex justify-content-between align-items-end">
              <div>
                <div className="small text-muted">{t('passes.from')}</div>
                <div className="fs-4 fw-bold">{formatINR(p.from_price)}</div>
                <FxHint amount={p.from_price} className="d-block" />
                <div className="small text-muted">{t('passes.perPerson')}</div>
              </div>
              <Link to={`/passes/${p.slug}`} className="btn btn-accent" aria-label={t('passes.viewAria', { name: p.name })}>
                {t('passes.view')}
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  private renderOrder(o: PassOrder): React.ReactNode {
    const { t } = this.props.i18n;
    const valid = o.status === 'confirmed';
    const used = o.sites.filter((s) => s.used).length;
    return (
      <div key={o.reference} className="card border-0 shadow-sm mb-3">
        <div className="card-body">
          <div className="row g-3 align-items-start">
            <div className="col-md-8">
              <div className="d-flex flex-wrap align-items-center gap-2 mb-1">
                <h3 className="h5 mb-0">{o.pass_name}</h3>
                <span className={`badge ${ORDER_BADGE[o.status]}`}>{t(`passes.status.${o.status}`)}</span>
              </div>
              <div className="small text-muted mb-2">
                <span className="ref">{o.reference}</span> ·{' '}
                {o.start_date === o.end_date
                  ? formatDate(o.start_date)
                  : `${formatDate(o.start_date)} – ${formatDate(o.end_date)}`}{' '}
                · {PASS_CATEGORIES.filter((c) => o.counts[c]).map((c) => `${o.counts[c]} × ${t(`passes.category.${c}`)}`).join(', ')}{' '}
                · {formatINR(o.total_amount)}
              </div>
              {valid && (
                <div className="small mb-1" aria-live="polite">{t('passes.mine.usedOf', { used, total: o.sites.length })}</div>
              )}
              <ul className="list-group list-group-flush small">
                {o.sites.map((s) => (
                  <li key={s.slug} className="list-group-item px-0 d-flex justify-content-between gap-2">
                    <span>
                      <i
                        className={`bi ${s.used ? 'bi-check-circle-fill text-success' : 'bi-circle text-muted'} me-2`}
                        aria-hidden="true"
                      />
                      <Link to={`/museums/${s.slug}`}>{s.name}</Link>
                    </span>
                    <span className={s.used ? 'text-success' : 'text-muted'}>
                      {s.used && s.visited_at ? t('passes.mine.visited', { at: formatDateTime(s.visited_at) }) : t('passes.mine.notYet')}
                    </span>
                  </li>
                ))}
              </ul>
              {Number(o.refund_amount) > 0 && (
                <div className="small text-success mt-2">
                  {t('passes.mine.refunded', { amount: formatINR(o.refund_amount), status: o.refund_status_label })}
                </div>
              )}
              <div className="d-flex flex-wrap gap-2 mt-3">
                {o.status === 'pending' && (
                  <Link to={`/passes/${o.pass_slug}?order=${o.reference}`} className="btn btn-accent btn-sm">
                    {t('passes.mine.payNow')}
                  </Link>
                )}
                {o.can_cancel && (
                  <button type="button" className="btn btn-outline-danger btn-sm" onClick={() => this.cancel(o)} disabled={this.state.busyRef === o.reference}>
                    {this.state.busyRef === o.reference ? t('passes.mine.cancelling') : t('passes.mine.cancel')}
                  </button>
                )}
              </div>
            </div>
            <div className="col-md-4 text-center">
              {valid ? (
                <>
                  <div className="qr d-inline-block p-2 bg-white rounded border">
                    <QRCodeSVG value={o.reference} size={140} />
                  </div>
                  <div className="ref mt-1">{o.reference}</div>
                  <div className="small text-muted">{t('passes.qrHint')}</div>
                </>
              ) : (
                <div className="small text-muted">{t('passes.mine.qrAfterPayment')}</div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { passes, error, orders, ordersError } = this.state;
    const user = this.props.auth.user;
    const visibleOrders = (orders ?? []).filter((o) => o.status !== 'expired');
    return (
      <div className="container py-4">
        <div className="mb-4">
          <h1 className="h2 mb-1">{t('passes.title')}</h1>
        {this.state.site && !this.state.site.passes_enabled && (
          <div className="alert alert-warning"><i className="bi bi-pause-circle me-2" aria-hidden="true" />{this.state.site.paused_message || t('common.paused.passes')}</div>
        )}
          <p className="text-muted mb-0">{t('passes.subtitle')}</p>
        </div>
        {error && <div className="alert alert-warning">{error}</div>}
        {passes === null ? (
          <Loader />
        ) : passes.length === 0 ? (
          <Empty title={t('passes.empty')} />
        ) : (
          <div className="row g-4 mb-5">{passes.map((p) => this.renderCard(p))}</div>
        )}

        <section id="my-passes" aria-labelledby="my-passes-title" className="mt-4">
          <h2 id="my-passes-title" className="h3 mb-3">{t('passes.mine.title')}</h2>
          {!user ? (
            <p className="text-muted">
              <Link to="/login" state={{ from: '/passes' }}>{t('passes.mine.login')}</Link> {t('passes.mine.loginAfter')}
            </p>
          ) : orders === null ? (
            <Loader />
          ) : (
            <>
              {ordersError && <div className="alert alert-danger" role="alert">{ordersError}</div>}
              {visibleOrders.length === 0 ? <p className="text-muted">{t('passes.mine.none')}</p> : visibleOrders.map((o) => this.renderOrder(o))}
            </>
          )}
        </section>
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(Passes)));
