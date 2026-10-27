import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { buyMembership, fetchMyMemberships, fetchPlans } from '../../api/memberships';
import type { Membership as MembershipCard, MembershipPlan } from '../../api/memberships';
import { openRazorpay, RazorpayOrder } from '../../api/razorpay';
import AuthModal from '../../components/AuthModal';
import { Empty, Loader } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatINR } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

/*
 * Heritage Card (annual membership): plan cards, then pay right here (Razorpay when configured, otherwise the
 * demo gateway) and show the digital card with a QR of the card number. ?card=AAM-XXXX-XXXX resumes paying.
 */

const METHODS = ['upi', 'card', 'netbanking'];
const BRAND_COLOR = '#0277bd'; // matches $primary in theme.scss

interface PaymentConfig {
  provider: 'razorpay' | 'mock';
  test_mode: boolean;
  refund_full_before_hours: number;
}

type MembershipProps = WithRouterProps & WithAuthProps & WithI18nProps;

interface MembershipState {
  plans: MembershipPlan[] | null;
  loadError: boolean;
  mine: MembershipCard[];
  /** Plan waiting for sign-in before the purchase starts. */
  pendingPlan: MembershipPlan | null;
  holderName: string;
  authOpen: boolean;
  submitting: boolean;
  /** The purchase being paid (or just paid). */
  order: MembershipCard | null;
  config: PaymentConfig | null;
  method: string;
  paying: boolean;
  error: string;
  info: string;
}

class Membership extends React.Component<MembershipProps, MembershipState> {
  public state: MembershipState = {
    plans: null,
    loadError: false,
    mine: [],
    pendingPlan: null,
    holderName: this.nameFromUser(),
    authOpen: false,
    submitting: false,
    order: null,
    config: null,
    method: 'upi',
    paying: false,
    error: '',
    info: '',
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    fetchPlans()
      .then((plans) => this.mounted && this.setState({ plans }))
      .catch(() => this.mounted && this.setState({ plans: [], loadError: true }));
    api
      .get<PaymentConfig>('/payments/config/')
      .then(({ data }) => this.mounted && this.setState({ config: data }))
      .catch(() => this.mounted && this.setState({ config: { provider: 'mock', test_mode: false, refund_full_before_hours: 24 } }));
    this.loadMine();
  }

  public componentDidUpdate(prevProps: MembershipProps): void {
    if (prevProps.auth.user !== this.props.auth.user && this.props.auth.user) {
      if (!this.state.holderName) this.setState({ holderName: this.nameFromUser() });
      this.loadMine();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private nameFromUser(): string {
    const u = this.props.auth.user;
    return u ? `${u.first_name} ${u.last_name}`.trim() : '';
  }

  /** The visitor's cards, and ?card=... to continue paying one started earlier. */
  private loadMine(): void {
    if (!this.props.auth.user) return;
    fetchMyMemberships()
      .then((mine) => {
        if (!this.mounted) return;
        const ref = (this.props.router.searchParams.get('card') ?? '').toUpperCase();
        const resume = ref ? mine.find((m) => m.card_number === ref) ?? null : null;
        this.setState({ mine, order: this.state.order ?? resume });
      })
      .catch(() => undefined);
  }

  private choose = (plan: MembershipPlan): void => {
    this.setState({ pendingPlan: plan, error: '', info: '' });
    if (!this.props.auth.user) this.setState({ authOpen: true });
    else this.createOrder(plan);
  };

  private createOrder = async (plan: MembershipPlan | null = this.state.pendingPlan): Promise<void> => {
    if (!plan) return;
    this.setState({ authOpen: false, submitting: true, error: '', info: '' });
    try {
      const order = await buyMembership(plan.slug, this.state.holderName.trim() || this.nameFromUser());
      if (!this.mounted) return;
      this.setState({ order, pendingPlan: null });
      this.props.router.setSearchParams({ card: order.card_number }, { replace: true });
      if (order.status === 'active') this.loadMine();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ submitting: false });
    }
  };

  private pay = async (): Promise<void> => {
    const { order } = this.state;
    if (!order) return;
    const { t } = this.props.i18n;
    const base = `/memberships/${order.card_number}`;
    this.setState({ paying: true, error: '', info: '' });
    try {
      const { data: rz } = await api.post<RazorpayOrder | { provider: 'mock' }>(`${base}/payment-order/`);
      let paid: MembershipCard;
      if (rz.provider === 'razorpay') {
        const result = await openRazorpay(rz, BRAND_COLOR);
        if (!result) {
          if (this.mounted) this.setState({ paying: false, info: t('booking.checkout.windowClosed') });
          return;
        }
        if (this.mounted) this.setState({ info: t('booking.checkout.confirming') });
        ({ data: paid } = await api.post<MembershipCard>(`${base}/pay/`, result));
      } else {
        // Demo gateway (no Razorpay keys configured): no real money moves.
        await new Promise((r) => setTimeout(r, 600));
        ({ data: paid } = await api.post<MembershipCard>(`${base}/pay/`, { method: this.state.method }));
      }
      if (!this.mounted) return;
      this.setState({ order: paid, paying: false, info: '' });
      this.loadMine();
    } catch (err) {
      const message = err instanceof Error && !('isAxiosError' in err) ? err.message : errorMessage(err);
      if (this.mounted) this.setState({ error: message, paying: false, info: '' });
    }
  };

  private startOver = (): void => {
    this.setState({ order: null, error: '', info: '' });
    this.props.router.setSearchParams({}, { replace: true });
  };

  private benefits(p: MembershipPlan): string[] {
    const { t } = this.props.i18n;
    return [
      p.free_entry ? t('shop.membership.benefit.free') : t('shop.membership.benefit.discount', { n: p.discount_percent }),
      p.max_visitors_per_booking === 1
        ? t('shop.membership.benefit.visitors.one')
        : t('shop.membership.benefit.visitors.other', { n: p.max_visitors_per_booking }),
      p.all_places
        ? t('shop.membership.benefit.allPlaces')
        : t('shop.membership.benefit.somePlaces', { n: p.places.length, names: p.places.map((m) => m.name).join(', ') }),
      t('shop.membership.benefit.auto'),
    ];
  }

  /** The digital membership card: holder, number, validity and a QR of the card number. */
  private renderCard(m: MembershipCard): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <div key={m.card_number} className="heritage-card shadow">
        <div className="d-flex justify-content-between align-items-start gap-3">
          <div className="min-w-0">
            <div className="hc-brand"><i className="bi bi-award-fill me-1" aria-hidden="true" />ANCIENT ANTIQUITY</div>
            <div className="hc-plan">{m.plan_name}</div>
          </div>
          <span className={`badge ${m.status === 'active' ? 'bg-accent' : 'bg-secondary'}`}>{t(`shop.membership.status.${m.status}`)}</span>
        </div>
        <div className="d-flex justify-content-between align-items-end gap-3 mt-3">
          <dl className="mb-0 small">
            <dt>{t('shop.membership.card.member')}</dt>
            <dd className="fs-5 fw-semibold mb-1">{m.holder_name}</dd>
            <dt>{t('shop.membership.card.number')}</dt>
            <dd className="hc-number mb-1">{m.card_number}</dd>
            {m.starts_on && m.ends_on && (
              <>
                <dt>{t('shop.membership.card.validTill')}</dt>
                <dd className="mb-0 fw-semibold">{formatDate(m.ends_on)}</dd>
              </>
            )}
          </dl>
          <div className="hc-qr flex-shrink-0">
            <QRCodeSVG value={m.card_number} size={96} />
          </div>
        </div>
        {m.starts_on && m.ends_on && new Date(`${m.starts_on}T00:00:00`) > new Date() && (
          <div className="small mt-2">{t('shop.membership.card.validFrom')} {formatDate(m.starts_on)}</div>
        )}
      </div>
    );
  }

  private renderPayment(order: MembershipCard): React.ReactNode {
    const { t } = this.props.i18n;
    const { config, method, paying, error, info } = this.state;
    const live = config?.provider === 'razorpay';
    if (order.status === 'active') {
      return (
        <div className="row g-4 align-items-center">
          <div className="col-md-6">{this.renderCard(order)}</div>
          <div className="col-md-6">
            <div className="alert alert-success" role="status">
              <i className="bi bi-check-circle-fill me-2" aria-hidden="true" />
              {t('shop.membership.card.done')}
            </div>
            <p className="small text-muted">{t('shop.membership.card.qrHint')}</p>
            <div className="d-flex flex-wrap gap-2">
              <Link to="/museums" className="btn btn-accent">{t('shop.membership.card.explore')}</Link>
              <button type="button" className="btn btn-outline-primary" onClick={this.startOver}>{t('shop.membership.pay.change')}</button>
            </div>
          </div>
        </div>
      );
    }
    if (order.status !== 'pending') {
      return (
        <div className="alert alert-warning mb-0">
          {t('shop.membership.pay.notPayable', { status: t(`shop.membership.status.${order.status}`) })}{' '}
          <button type="button" className="btn btn-link p-0 align-baseline" onClick={this.startOver}>{t('shop.membership.pay.startAgain')}</button>
        </div>
      );
    }
    return (
      <div style={{ maxWidth: 520 }}>
        <h2 className="h4 mb-3">{t('shop.membership.pay.title', { name: order.plan_name })}</h2>
        <p className="small text-muted mb-3">
          {t('shop.membership.card.member')}: <strong className="text-body">{order.holder_name}</strong> · <span className="ref">{order.card_number}</span>
        </p>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        {info && <div className="alert alert-info">{info}</div>}
        {live ? (
          <p className="text-muted small">
            {t('booking.checkout.razorpayIntro')}
            {config?.test_mode && <span className="badge bg-warning ms-2">{t('booking.checkout.testMode')}</span>}
          </p>
        ) : (
          <div className="list-group mb-3">
            {METHODS.map((m) => (
              <label key={m} className={`list-group-item list-group-item-action d-flex gap-3 align-items-center py-2 ${method === m ? 'active' : ''}`}>
                <input className="form-check-input flex-shrink-0 mt-0" type="radio" name="card-method" value={m} checked={method === m} onChange={() => this.setState({ method: m })} />
                <span>
                  <strong className="d-block">{t(`booking.method.${m}`)}</strong>
                  <small className={method === m ? '' : 'text-muted'}>{t(`booking.method.${m}.hint`)}</small>
                </span>
              </label>
            ))}
          </div>
        )}
        <button className="btn btn-accent btn-lg w-100" onClick={this.pay} disabled={paying || !config}>
          <i className="bi bi-lock-fill me-2" aria-hidden="true" />
          {paying ? t('booking.checkout.processing') : t('booking.checkout.pay', { amount: formatINR(order.total_amount) })}
        </button>
        <p className="text-muted small mt-2 mb-2">{live ? t('booking.checkout.razorpayNote') : t('booking.checkout.demoNote')}</p>
        <button type="button" className="btn btn-link btn-sm p-0" onClick={this.startOver} disabled={paying}>
          {t('shop.membership.pay.change')}
        </button>
      </div>
    );
  }

  private renderPlans(plans: MembershipPlan[], hasActive: boolean): React.ReactNode {
    const { t } = this.props.i18n;
    const { submitting, pendingPlan, holderName } = this.state;
    return (
      <>
        {this.props.auth.user && (
          <div className="mb-3" style={{ maxWidth: 360 }}>
            <label htmlFor="hc-holder" className="form-label small fw-semibold">{t('shop.membership.holder')}</label>
            <input id="hc-holder" className="form-control" value={holderName} maxLength={120} autoComplete="name"
              onChange={(e) => this.setState({ holderName: e.target.value })} />
          </div>
        )}
        <div className="row g-4">
          {plans.map((p) => (
            <div key={p.id} className="col-md-6 col-lg-4">
              <div className="card border-0 shadow-sm h-100 membership-plan">
                <div className="card-body p-4 d-flex flex-column">
                  <h2 className="h5 mb-1">{p.name}</h2>
                  <div className="mb-2">
                    <span className="fs-3 fw-bold text-accent">{formatINR(p.price)}</span>{' '}
                    <span className="text-muted small">
                      {p.duration_days === 365 ? t('shop.membership.perYear') : t('shop.membership.forDays', { n: p.duration_days })}
                    </span>
                  </div>
                  {p.description && <p className="text-muted small">{p.description}</p>}
                  <ul className="list-unstyled small mb-4 flex-grow-1">
                    {this.benefits(p).map((b) => (
                      <li key={b} className="d-flex gap-2 mb-1">
                        <i className="bi bi-check-circle-fill text-success" aria-hidden="true" />
                        <span>{b}</span>
                      </li>
                    ))}
                  </ul>
                  <button type="button" className="btn btn-accent w-100" disabled={submitting} onClick={() => this.choose(p)}>
                    <i className="bi bi-award me-2" aria-hidden="true" />
                    {submitting && pendingPlan?.id === p.id ? t('shop.membership.creating') : hasActive ? t('shop.membership.renew') : t('shop.membership.buy')}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
        {hasActive && <p className="small text-muted mt-3">{t('shop.membership.renewHint')}</p>}
        <p className="small text-muted mt-2 mb-0">{t('shop.membership.terms')}</p>
      </>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { plans, loadError, mine, order, authOpen, pendingPlan, error, holderName } = this.state;
    const valid = mine.filter((m) => m.status === 'active');
    return (
      <div className="container page py-4 py-lg-5">
        <div className="mb-4">
          <h1 className="display-6 mb-1">{t('shop.membership.title')}</h1>
          <p className="lead text-muted mb-0">{t('shop.membership.subtitle')}</p>
        </div>

        {order && (
          <div className="card border-0 shadow-sm mb-4">
            <div className="card-body p-4">{this.renderPayment(order)}</div>
          </div>
        )}

        {!order && valid.length > 0 && (
          <section className="mb-5" aria-labelledby="my-cards">
            <h2 id="my-cards" className="h4 mb-3">{t('shop.membership.mine')}</h2>
            <div className="row g-4">
              {valid.map((m) => (
                <div key={m.card_number} className="col-md-6 col-lg-5">{this.renderCard(m)}</div>
              ))}
            </div>
            <p className="small text-muted mt-3 mb-0">{t('shop.membership.card.qrHint')}</p>
          </section>
        )}

        {!order && error && <div className="alert alert-danger" role="alert">{error}</div>}
        {!order && (plans === null ? (
          <Loader />
        ) : loadError ? (
          <div className="alert alert-danger">{t('shop.membership.loadError')}</div>
        ) : plans.length === 0 ? (
          <Empty title={t('shop.membership.empty')} />
        ) : (
          this.renderPlans(plans, valid.length > 0)
        ))}

        <AuthModal
          open={authOpen}
          title={t('shop.membership.auth.title')}
          reason={t('shop.membership.auth.reason')}
          prefill={{ name: holderName, email: '', phone: '' }}
          onClose={() => this.setState({ authOpen: false, pendingPlan: null })}
          onDone={() => this.createOrder(pendingPlan)}
        />
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(Membership)));
