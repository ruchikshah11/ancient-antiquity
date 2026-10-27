import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import { emptyCounts, PASS_CATEGORIES, PassCategory, PassCounts } from '../../api/passes';
import type { ComboPass, PassOrder } from '../../api/passes';
import { openRazorpay, RazorpayOrder } from '../../api/razorpay';
import AuthModal from '../../components/AuthModal';
import { Empty, Loader } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatINR, formatPrice, isoDate, museumGradient, placeLabel, sizedImage } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import FxHint from '../../components/FxHint';
import { placeLocation } from '../../utils/format';

/*
 * One combo pass: included places, date, visitors, then pay right here (Razorpay when configured,
 * otherwise the demo gateway) and show the pass QR. ?order=AP-XXXXXXXX resumes paying a pending order.
 */

const METHODS = ['upi', 'card', 'netbanking'];
const BRAND_COLOR = '#0277bd'; // matches $primary in theme.scss
const MAX_PARTY = 20;
const MAX_AHEAD_DAYS = 180;

interface PaymentConfig {
  provider: 'razorpay' | 'mock';
  test_mode: boolean;
  refund_full_before_hours: number;
}

interface Visitor {
  name: string;
  email: string;
  phone: string;
}

type PassDetailProps = WithRouterProps & WithAuthProps & WithI18nProps;

interface PassDetailState {
  pass: ComboPass | null;
  loading: boolean;
  notFound: boolean;
  date: string;
  counts: PassCounts;
  visitor: Visitor;
  authOpen: boolean;
  submitting: boolean;
  error: string;
  info: string;
  order: PassOrder | null;
  config: PaymentConfig | null;
  method: string;
  paying: boolean;
}

/** Adds n days to a YYYY-MM-DD date. */
function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

class PassDetail extends React.Component<PassDetailProps, PassDetailState> {
  public state: PassDetailState = {
    pass: null,
    loading: true,
    notFound: false,
    date: isoDate(1),
    counts: { ...emptyCounts(), indian: 1 },
    visitor: this.visitorFromUser(),
    authOpen: false,
    submitting: false,
    error: '',
    info: '',
    order: null,
    config: null,
    method: 'upi',
    paying: false,
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
    api
      .get<PaymentConfig>('/payments/config/')
      .then(({ data }) => this.mounted && this.setState({ config: data }))
      .catch(() => this.mounted && this.setState({ config: { provider: 'mock', test_mode: false, refund_full_before_hours: 24 } }));
    this.resumeOrder();
  }

  public componentDidUpdate(prevProps: PassDetailProps): void {
    if (prevProps.router.params.slug !== this.props.router.params.slug) this.load();
    if (prevProps.auth.user !== this.props.auth.user && this.props.auth.user) {
      const { visitor } = this.state;
      if (!visitor.name && !visitor.email) this.setState({ visitor: this.visitorFromUser() });
      this.resumeOrder();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private visitorFromUser(): Visitor {
    const u = this.props.auth.user;
    return u ? { name: `${u.first_name} ${u.last_name}`.trim(), email: u.email, phone: u.phone ?? '' } : { name: '', email: '', phone: '' };
  }

  private load(): void {
    const slug = this.props.router.params.slug ?? '';
    this.setState({ loading: true, notFound: false });
    cachedGet<ComboPass>(`/passes/${slug}/`, undefined, (data) => {
      if (this.mounted) this.setState({ pass: data, loading: false });
    }).catch(() => this.mounted && this.setState({ loading: false, notFound: true }));
  }

  /** ?order=AP-... : continue paying an order started earlier. */
  private resumeOrder(): void {
    const ref = this.props.router.searchParams.get('order');
    if (!ref || !this.props.auth.user) return;
    api
      .get<PassOrder>(`/pass-orders/${ref}/`)
      .then(({ data }) => this.mounted && this.setState({ order: data }))
      .catch(() => undefined);
  }

  private total(): number {
    const { pass, counts } = this.state;
    if (!pass) return 0;
    return PASS_CATEGORIES.reduce((sum, c) => sum + Number(pass.prices[c]) * counts[c], 0);
  }

  private people(): number {
    const { counts } = this.state;
    return PASS_CATEGORIES.reduce((n, c) => n + counts[c], 0);
  }

  private change(c: PassCategory, delta: number): void {
    const counts = { ...this.state.counts };
    const next = counts[c] + delta;
    if (next < 0 || (delta > 0 && this.people() >= MAX_PARTY)) return;
    counts[c] = next;
    this.setState({ counts, error: '' });
  }

  private setVisitor = (k: keyof Visitor) => (e: React.ChangeEvent<HTMLInputElement>): void =>
    this.setState({ visitor: { ...this.state.visitor, [k]: e.target.value } });

  private buy = (e: React.FormEvent): void => {
    e.preventDefault();
    if (this.people() < 1) {
      this.setState({ error: this.props.i18n.t('passes.detail.addVisitor') });
      return;
    }
    if (!this.props.auth.user) this.setState({ authOpen: true });
    else this.createOrder();
  };

  private createOrder = async (): Promise<void> => {
    const { pass, date, counts, visitor } = this.state;
    if (!pass) return;
    this.setState({ authOpen: false, submitting: true, error: '', info: '' });
    try {
      const { data } = await api.post<PassOrder>('/pass-orders/', {
        combo_pass: pass.slug,
        start_date: date,
        ...counts,
        visitor_name: visitor.name.trim() || this.visitorFromUser().name || visitor.email,
        visitor_email: visitor.email.trim(),
        visitor_phone: visitor.phone.trim(),
      });
      if (!this.mounted) return;
      this.setState({ order: data });
      this.props.router.setSearchParams({ order: data.reference }, { replace: true });
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
    this.setState({ paying: true, error: '', info: '' });
    try {
      const { data: rz } = await api.post<RazorpayOrder | { provider: 'mock' }>(`/pass-orders/${order.reference}/payment-order/`);
      let paid: PassOrder;
      if (rz.provider === 'razorpay') {
        const result = await openRazorpay(rz, BRAND_COLOR);
        if (!result) {
          if (this.mounted) this.setState({ paying: false, info: t('booking.checkout.windowClosed') });
          return;
        }
        if (this.mounted) this.setState({ info: t('booking.checkout.confirming') });
        ({ data: paid } = await api.post<PassOrder>(`/pass-orders/${order.reference}/pay/`, result));
      } else {
        await new Promise((r) => setTimeout(r, 600));
        ({ data: paid } = await api.post<PassOrder>(`/pass-orders/${order.reference}/pay/`, { method: this.state.method }));
      }
      if (this.mounted) this.setState({ order: paid, paying: false, info: '' });
    } catch (err) {
      const message = err instanceof Error && !('isAxiosError' in err) ? err.message : errorMessage(err);
      if (this.mounted) this.setState({ error: message, paying: false, info: '' });
    }
  };

  private startOver = (): void => {
    this.setState({ order: null, error: '', info: '' });
    this.props.router.setSearchParams({}, { replace: true });
  };

  private renderSites(pass: ComboPass): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <ol className="list-group list-group-numbered mb-4">
        {pass.sites.map((s) => (
          <li key={s.slug} className="list-group-item d-flex gap-3 align-items-center">
            <div
              className="rounded flex-shrink-0"
              style={{
                width: 64, height: 48,
                background: s.image_url ? `center / cover no-repeat url("${sizedImage(s.image_url, 330)}")` : museumGradient(s.slug),
              }}
              aria-hidden="true"
            />
            <div className="min-w-0 flex-grow-1">
              <Link to={`/museums/${s.slug}`} className="fw-semibold">{s.name}</Link>
              <div className="small text-muted">
                {placeLabel(s.place_type)} · <i className="bi bi-geo-alt" aria-hidden="true" /> {placeLocation(s.city_name, s.state_name)}
              </div>
            </div>
          </li>
        ))}
        <li className="visually-hidden">{t('passes.detail.siteCount', { n: pass.sites.length })}</li>
      </ol>
    );
  }

  private renderBuyForm(pass: ComboPass): React.ReactNode {
    const { t } = this.props.i18n;
    const { date, counts, visitor, submitting, error } = this.state;
    const end = addDays(date, pass.validity_days - 1);
    const people = this.people();
    return (
      <form onSubmit={this.buy} noValidate={false}>
        <h2 className="h4 mb-3">{t('passes.detail.buyTitle')}</h2>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        <div className="mb-3">
          <label htmlFor="pass-date" className="form-label">{t('passes.detail.firstDay')}</label>
          <input
            id="pass-date" type="date" className="form-control" value={date} min={isoDate(0)} max={isoDate(MAX_AHEAD_DAYS)}
            onChange={(e) => this.setState({ date: e.target.value, error: '' })} required
          />
          <div className="form-text">
            <i className="bi bi-calendar-range me-1" aria-hidden="true" />
            {pass.validity_days > 1
              ? t('passes.detail.validRange', { from: formatDate(date), to: formatDate(end), n: pass.validity_days })
              : t('passes.detail.validOneDay', { date: formatDate(date) })}
          </div>
        </div>

        <div className="mb-3">
          <span className="form-label d-block mb-1">{t('passes.detail.visitors')}</span>
          {PASS_CATEGORIES.map((c) => {
            const label = t(`passes.category.${c}`);
            return (
              <div key={c} className="d-flex justify-content-between align-items-center py-2 border-bottom">
                <div>
                  <div className="fw-semibold">{label}</div>
                  <div className="small text-muted">
                    {formatPrice(pass.prices[c])}
                    {c === 'student' && <> · {t('passes.category.studentHint')}</>}
                    {c === 'child' && <> · {t('passes.category.childHint')}</>}
                  </div>
                </div>
                <div className="input-group input-group-sm flex-nowrap" style={{ width: 110 }}>
                  <button type="button" className="btn btn-outline-primary" aria-label={t('passes.detail.fewer', { name: label })} disabled={!counts[c]} onClick={() => this.change(c, -1)}>−</button>
                  <span className="form-control text-center bg-white" aria-live="polite">{counts[c]}</span>
                  <button type="button" className="btn btn-outline-primary" aria-label={t('passes.detail.more', { name: label })} disabled={people >= MAX_PARTY} onClick={() => this.change(c, 1)}>+</button>
                </div>
              </div>
            );
          })}
          {people >= MAX_PARTY && <div className="small text-muted mt-2">{t('passes.detail.maxParty', { n: MAX_PARTY })}</div>}
        </div>

        <div className="row g-2 mb-3">
          <div className="col-12">
            <label htmlFor="pass-name" className="form-label">{t('passes.detail.name')}</label>
            <input id="pass-name" className="form-control" value={visitor.name} onChange={this.setVisitor('name')} autoComplete="name" required maxLength={120} />
          </div>
          <div className="col-sm-7">
            <label htmlFor="pass-email" className="form-label">{t('passes.detail.email')}</label>
            <input id="pass-email" type="email" className="form-control" value={visitor.email} onChange={this.setVisitor('email')} autoComplete="email" />
          </div>
          <div className="col-sm-5">
            <label htmlFor="pass-phone" className="form-label">{t('passes.detail.phone')}</label>
            <input id="pass-phone" type="tel" className="form-control" value={visitor.phone} onChange={this.setVisitor('phone')} autoComplete="tel" maxLength={15} />
          </div>
        </div>

        <div className="d-flex justify-content-between align-items-center fs-5 fw-bold mb-3">
          <span>{t('passes.detail.total')}</span>
          <span className="text-end">{formatINR(this.total())}<FxHint amount={this.total()} className="d-block fs-6 fw-normal" /></span>
        </div>
        <button className="btn btn-accent btn-lg w-100" disabled={submitting || people < 1}>
          <i className="bi bi-wallet2 me-2" aria-hidden="true" />
          {submitting ? t('passes.detail.creating') : t('passes.detail.buy')}
        </button>
        <p className="small text-muted mt-2 mb-0">{t('passes.detail.policy')}</p>
      </form>
    );
  }

  private renderPayment(order: PassOrder): React.ReactNode {
    const { t } = this.props.i18n;
    const { config, method, paying, error, info } = this.state;
    const live = config?.provider === 'razorpay';
    return (
      <div>
        <h2 className="h4 mb-3">{t('passes.pay.title')}</h2>
        <dl className="row small mb-3">
          <dt className="col-5 fw-normal text-muted">{t('passes.pay.reference')}</dt>
          <dd className="col-7 ref mb-1">{order.reference}</dd>
          <dt className="col-5 fw-normal text-muted">{t('passes.pay.valid')}</dt>
          <dd className="col-7 mb-1">
            {order.start_date === order.end_date ? formatDate(order.start_date) : `${formatDate(order.start_date)} – ${formatDate(order.end_date)}`}
          </dd>
          <dt className="col-5 fw-normal text-muted">{t('passes.pay.visitors')}</dt>
          <dd className="col-7 mb-1">
            {PASS_CATEGORIES.filter((c) => order.counts[c]).map((c) => `${order.counts[c]} × ${t(`passes.category.${c}`)}`).join(', ')}
          </dd>
        </dl>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        {info && <div className="alert alert-info">{info}</div>}
        {order.status === 'pending' ? (
          <>
            {live ? (
              <p className="text-muted small">
                {t('booking.checkout.razorpayIntro')}
                {config?.test_mode && <span className="badge bg-warning ms-2">{t('booking.checkout.testMode')}</span>}
              </p>
            ) : (
              <div className="list-group mb-3">
                {METHODS.map((m) => (
                  <label key={m} className={`list-group-item list-group-item-action d-flex gap-3 align-items-center py-2 ${method === m ? 'active' : ''}`}>
                    <input className="form-check-input flex-shrink-0 mt-0" type="radio" name="pass-method" value={m} checked={method === m} onChange={() => this.setState({ method: m })} />
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
            <p className="text-muted small mt-2 mb-2">
              {live ? t('booking.checkout.razorpayNote') : t('booking.checkout.demoNote')}
            </p>
            <button type="button" className="btn btn-link btn-sm p-0" onClick={this.startOver} disabled={paying}>
              {t('passes.pay.change')}
            </button>
          </>
        ) : order.status === 'confirmed' ? (
          <div className="text-center">
            <div className="alert alert-success text-start" role="status">
              <i className="bi bi-check-circle-fill me-2" aria-hidden="true" />
              {t('passes.pay.done')}
            </div>
            <div className="qr d-inline-block p-2 bg-white rounded border">
              <QRCodeSVG value={order.reference} size={160} />
            </div>
            <div className="ref mt-2">{order.reference}</div>
            <p className="small text-muted">{t('passes.qrHint')}</p>
            <Link to="/passes#my-passes" className="btn btn-outline-primary">{t('passes.pay.seeMine')}</Link>
          </div>
        ) : (
          <div className="alert alert-warning">
            {t('passes.pay.notPayable', { status: t(`passes.status.${order.status}`) })}{' '}
            <button type="button" className="btn btn-link p-0 align-baseline" onClick={this.startOver}>{t('passes.pay.startAgain')}</button>
          </div>
        )}
      </div>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { pass, loading, notFound, order, authOpen, visitor } = this.state;
    if (loading && !pass) return <Loader />;
    if (notFound || !pass) {
      return (
        <div className="container py-5">
          <Empty title={t('passes.detail.notFound')}>
            <Link to="/passes" className="btn btn-primary mt-2">{t('passes.detail.allPasses')}</Link>
          </Empty>
        </div>
      );
    }
    return (
      <div className="container py-4">
        <nav aria-label="breadcrumb">
          <ol className="breadcrumb small">
            <li className="breadcrumb-item"><Link to="/passes">{t('passes.title')}</Link></li>
            <li className="breadcrumb-item active" aria-current="page">{pass.name}</li>
          </ol>
        </nav>
        <div className="row g-4">
          <div className="col-lg-7">
            <div
              className="rounded-3 mb-3 d-flex align-items-end p-3 text-white"
              style={{
                minHeight: 220,
                background: pass.image_url
                  ? `linear-gradient(transparent 40%, rgba(0,0,0,.7)), center / cover no-repeat url("${sizedImage(pass.image_url, 960)}")`
                  : museumGradient(pass.slug),
              }}
            >
              <div>
                <span className="badge bg-accent mb-2">
                  {pass.validity_days > 1 ? t('passes.validDays', { n: pass.validity_days }) : t('passes.validOneDay')}
                </span>
                <h1 className="h2 mb-0">{pass.name}</h1>
              </div>
            </div>
            <p className="lead">{pass.description}</p>
            <h2 className="h5 mb-3">{t('passes.detail.included', { n: pass.sites.length })}</h2>
            {this.renderSites(pass)}
            <div className="alert alert-info small d-flex gap-2">
              <i className="bi bi-info-circle" aria-hidden="true" />
              <span>{t('passes.detail.howItWorks', { n: pass.validity_days })}</span>
            </div>
          </div>
          <div className="col-lg-5">
            <div className="card border-0 shadow-sm sticky-lg-top" style={{ top: 80 }}>
              <div className="card-body p-4">
                {order ? this.renderPayment(order) : this.renderBuyForm(pass)}
              </div>
            </div>
          </div>
        </div>
        <AuthModal
          open={authOpen}
          title={t('passes.auth.title')}
          reason={t('passes.auth.reason', { name: pass.name })}
          prefill={visitor}
          onClose={() => this.setState({ authOpen: false })}
          onDone={this.createOrder}
        />
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(PassDetail)));
