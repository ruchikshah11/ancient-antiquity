import * as React from 'react';
import { Link } from 'react-router-dom';
import { addonLimit, AddOn, fetchPlaceAddOns, saveBookingAddOns } from '../../api/addons';
import { track } from '../../api/analytics';
import { api, errorMessage } from '../../api/client';
import { openRazorpay, RazorpayOrder } from '../../api/razorpay';
import type { Booking } from '../../api/types';
import type { PromoBooking } from '../../api/promotions';
import { Empty, Loader, StatusBadge } from '../../components/Common';
import { GroupPriceLines, groupHeadcount } from '../../components/GroupSummary';
import { formatDate, formatDateTime, formatINR, formatTime } from '../../utils/format';
import { withI18n, WithI18nProps } from '../../i18n';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import FxHint from '../../components/FxHint';
import { placeLocation } from '../../utils/format';

/** Label and hint of each method are i18n keys: booking.method.<id> and booking.method.<id>.hint. */
const METHODS = ['upi', 'card', 'netbanking'];

type CheckoutProps = WithRouterProps & WithI18nProps;

interface PaymentConfig {
  provider: 'razorpay' | 'mock';
  test_mode: boolean;
  refund_full_before_hours: number;
}

interface CheckoutState {
  booking: Booking | null | undefined;
  config: PaymentConfig | null;
  method: string;
  error: string;
  info: string;
  paying: boolean;
  secondsLeft: number;
  /* promo code / gift voucher box */
  codeOpen: boolean;
  code: string;
  codeBusy: boolean;
  codeError: string;
  codeInfo: string;
  /* add-ons offered by the place, and the visitor's (possibly unsaved) choice: addon id -> quantity */
  addons: AddOn[];
  picks: Record<number, number>;
  addonsBusy: boolean;
  addonsError: string;
  addonsInfo: string;
}

const BRAND_COLOR = '#0277bd'; // matches $primary in theme.scss

class Checkout extends React.Component<CheckoutProps, CheckoutState> {
  public state: CheckoutState = {
    booking: undefined,
    config: null,
    method: 'upi',
    error: '',
    info: '',
    paying: false,
    secondsLeft: 0,
    codeOpen: false,
    code: '',
    codeBusy: false,
    codeError: '',
    codeInfo: '',
    addons: [],
    picks: {},
    addonsBusy: false,
    addonsError: '',
    addonsInfo: '',
  };

  private mounted = false;
  private requestId = 0;
  private timer: ReturnType<typeof setInterval> | null = null;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
    track('view_checkout', { booking: this.props.router.params.reference });
    api
      .get<PaymentConfig>('/payments/config/')
      .then((r) => this.mounted && this.setState({ config: r.data }))
      .catch(() => this.mounted && this.setState({ config: { provider: 'mock', test_mode: false, refund_full_before_hours: 24 } }));
  }

  public componentDidUpdate(prevProps: CheckoutProps, prevState: CheckoutState): void {
    if (prevProps.router.params.reference !== this.props.router.params.reference) this.load();
    // Countdown restarts whenever the hold expiry changes.
    const prevUntil = prevState.booking?.hold_expires_at ?? null;
    const until = this.state.booking?.hold_expires_at ?? null;
    if (prevUntil !== until) this.startCountdown(until);
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    this.stopCountdown();
  }

  private get reference(): string | undefined {
    return this.props.router.params.reference;
  }

  private load(): void {
    const id = ++this.requestId;
    const reference = this.reference;
    api
      .get<Booking>(`/bookings/${reference}/`)
      .then((r) => {
        if (!this.mounted || id !== this.requestId) return;
        if (r.data.status !== 'pending') this.props.router.navigate(`/tickets/${reference}`, { replace: true });
        else {
          this.setState({ booking: r.data, picks: this.picksOf(r.data) });
          this.loadAddOns(r.data);
        }
      })
      .catch(() => {
        if (this.mounted && id === this.requestId) this.setState({ booking: null });
      });
  }

  private picksOf(booking: Booking): Record<number, number> {
    const picks: Record<number, number> = {};
    (booking.addons ?? []).forEach((a) => {
      picks[a.addon] = a.quantity;
    });
    return picks;
  }

  /** The place's add-ons, with what is left on the visit date (this booking's own choice not counted). */
  private loadAddOns(booking: Booking): void {
    fetchPlaceAddOns(booking.museum_slug, booking.visit_date, booking.reference)
      .then((addons) => this.mounted && this.setState({ addons }))
      .catch(() => undefined); // add-ons are optional: checkout works without them
  }

  /** Has the visitor changed the add-ons without saving them yet? */
  private addonsDirty(): boolean {
    const { booking, picks } = this.state;
    if (!booking) return false;
    const saved = this.picksOf(booking);
    const ids = new Set([...Object.keys(saved), ...Object.keys(picks)].map(Number));
    return [...ids].some((id) => (saved[id] ?? 0) !== (picks[id] ?? 0));
  }

  private setPick(a: AddOn, quantity: number): void {
    this.setState({ picks: { ...this.state.picks, [a.id]: quantity }, addonsInfo: '', addonsError: '' });
  }

  private saveAddOns = async (): Promise<void> => {
    const reference = this.reference;
    if (!reference) return;
    const items = Object.entries(this.state.picks)
      .filter(([, q]) => q > 0)
      .map(([id, quantity]) => ({ addon: Number(id), quantity }));
    this.setState({ addonsBusy: true, addonsError: '', addonsInfo: '' });
    try {
      const data = await saveBookingAddOns(reference, items);
      if (!this.mounted) return;
      if (data.status !== 'pending') {
        this.props.router.navigate(`/tickets/${reference}`, { replace: true });
        return;
      }
      this.setState({ booking: data, picks: this.picksOf(data), addonsBusy: false, addonsInfo: this.props.i18n.t('shop.addons.saved') });
      this.loadAddOns(data);
    } catch (err) {
      if (this.mounted) this.setState({ addonsBusy: false, addonsError: errorMessage(err) });
    }
  };

  private renderAddOns(booking: Booking, disabled: boolean): React.ReactNode {
    const { addons, picks, addonsBusy, addonsError, addonsInfo } = this.state;
    const { t } = this.props.i18n;
    if (!addons.length) return null;
    const dirty = this.addonsDirty();
    return (
      <section className="addon-picker mb-4" aria-labelledby="addons-title">
        <h3 id="addons-title" className="h5 mb-1">{t('shop.addons.title')}</h3>
        <p className="text-muted small mb-2">{t('shop.addons.intro')}</p>
        <ul className="list-group mb-2">
          {addons.map((a) => {
            const limit = addonLimit(a, booking.total_visitors);
            const qty = picks[a.id] ?? 0;
            const free = Number(a.price) <= 0;
            return (
              <li key={a.id} className={`list-group-item d-flex gap-3 align-items-center ${qty > 0 ? 'chosen' : ''}`}>
                <span className="addon-icon flex-shrink-0" aria-hidden="true"><i className={`bi bi-${a.icon}`} /></span>
                <div className="flex-grow-1 min-w-0">
                  <div className="fw-semibold">{a.name}</div>
                  <div className="small text-muted">
                    {free ? t('shop.addons.free') : <>{formatINR(a.price)} {t(a.per === 'person' ? 'shop.addons.perPerson' : 'shop.addons.perBooking')}</>}
                    {a.remaining !== null && (
                      <> · <span className={a.remaining === 0 ? 'text-danger' : ''}>{a.remaining === 0 ? t('shop.addons.soldOut') : t('shop.addons.left', { n: a.remaining })}</span></>
                    )}
                  </div>
                  {a.description && <div className="small text-muted">{a.description}</div>}
                </div>
                <div className="input-group input-group-sm flex-nowrap" style={{ width: 110 }}>
                  <button type="button" className="btn btn-outline-primary" aria-label={t('shop.addons.fewer', { name: a.name })}
                    disabled={disabled || addonsBusy || qty <= 0} onClick={() => this.setPick(a, qty - 1)}>−</button>
                  <span className="form-control text-center bg-white" aria-live="polite">{qty}</span>
                  <button type="button" className="btn btn-outline-primary" aria-label={t('shop.addons.more', { name: a.name })}
                    disabled={disabled || addonsBusy || qty >= limit} onClick={() => this.setPick(a, qty + 1)}>+</button>
                </div>
              </li>
            );
          })}
        </ul>
        {addonsError && <div className="text-danger small mb-2" role="alert">{addonsError}</div>}
        {addonsInfo && !dirty && <div className="text-success small mb-2" role="status">{addonsInfo}</div>}
        {dirty && (
          <div className="d-flex flex-wrap align-items-center gap-2">
            <button type="button" className="btn btn-primary btn-sm" onClick={this.saveAddOns} disabled={disabled || addonsBusy}>
              {addonsBusy ? t('shop.addons.saving') : t('shop.addons.save')}
            </button>
            <span className="small text-muted">{t('shop.addons.unsaved')}</span>
          </div>
        )}
      </section>
    );
  }

  /** Heritage Card discount and add-on lines in the order summary. */
  private renderExtraLines(booking: Booking): React.ReactNode {
    const { t } = this.props.i18n;
    const member = Number(booking.membership_discount ?? 0);
    const lines = booking.addons ?? [];
    return (
      <>
        {member > 0 && (
          <div className="d-flex justify-content-between py-2 border-bottom text-success">
            <span>
              <i className="bi bi-award-fill me-1" aria-hidden="true" />
              {t('shop.member.discountLine')}
              {booking.membership_card && <span className="small text-muted ms-1">({booking.membership_card})</span>}
            </span>
            <span>−{formatINR(member)}</span>
          </div>
        )}
        {lines.map((a) => (
          <div key={a.addon} className="d-flex justify-content-between align-items-center py-2 border-bottom">
            <span><i className={`bi bi-${a.icon} me-2 text-muted`} aria-hidden="true" />{a.quantity} × {a.name}</span>
            <span>{Number(a.line_total) > 0 ? formatINR(a.line_total) : t('shop.addons.free')}</span>
          </div>
        ))}
      </>
    );
  }

  private startCountdown(until: string | null): void {
    this.stopCountdown();
    if (!until) return;
    const tick = (): void => this.setState({ secondsLeft: Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 1000)) });
    tick();
    this.timer = setInterval(tick, 1000);
  }

  private stopCountdown(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private pay = async (): Promise<void> => {
    this.setState({ paying: true, error: '', info: '' });
    const reference = this.reference;
    try {
      const { data: order } = await api.post<RazorpayOrder | { provider: 'mock' }>(`/bookings/${reference}/payment-order/`);
      if (order.provider === 'razorpay') {
        // Real payment: Razorpay's window collects UPI/card/netbanking; the server then verifies the signature.
        const result = await openRazorpay(order, BRAND_COLOR);
        if (!result) {
          if (this.mounted) this.setState({ paying: false, info: this.props.i18n.t('booking.checkout.windowClosed') });
          return;
        }
        if (this.mounted) this.setState({ info: this.props.i18n.t('booking.checkout.confirming') });
        await api.post(`/bookings/${reference}/pay/`, result);
      } else {
        // Demo gateway (no Razorpay keys configured): no real money moves.
        await new Promise((r) => setTimeout(r, 900));
        await api.post(`/bookings/${reference}/pay/`, { method: this.state.method });
      }
      this.props.router.navigate(`/tickets/${reference}`, { replace: true });
    } catch (err) {
      const message = err instanceof Error && !('isAxiosError' in err) ? err.message : errorMessage(err);
      if (this.mounted) this.setState({ error: message, paying: false, info: '' });
    }
  };

  private applyCode = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const code = this.state.code.trim();
    if (!code) return;
    this.setState({ codeBusy: true, codeError: '', codeInfo: '' });
    try {
      const { data } = await api.post<Booking>(`/bookings/${this.reference}/apply-code/`, { code });
      if (!this.mounted) return;
      if (data.status !== 'pending') {
        // Code covered the whole amount: the booking is confirmed for free.
        this.setState({ booking: data, codeBusy: false, codeInfo: this.props.i18n.t('promo.coveredFree') });
        this.props.router.navigate(`/tickets/${this.reference}`, { replace: true });
        return;
      }
      this.setState({ booking: data, code: '', codeBusy: false, codeInfo: this.props.i18n.t('promo.applied') });
    } catch (err) {
      if (this.mounted) this.setState({ codeBusy: false, codeError: errorMessage(err) });
    }
  };

  private removeCode = async (kind: 'promo' | 'voucher'): Promise<void> => {
    this.setState({ codeBusy: true, codeError: '', codeInfo: '' });
    try {
      const { data } = await api.post<Booking>(`/bookings/${this.reference}/remove-code/`, { kind });
      if (this.mounted) this.setState({ booking: data, codeBusy: false, codeInfo: this.props.i18n.t('promo.removed') });
    } catch (err) {
      if (this.mounted) this.setState({ codeBusy: false, codeError: errorMessage(err) });
    }
  };

  private renderCodeBox(booking: PromoBooking, disabled: boolean): React.ReactNode {
    const { codeOpen, code, codeBusy, codeError, codeInfo } = this.state;
    const { t } = this.props.i18n;
    const hasPromo = !!booking.promo_code_text;
    const hasVoucher = Number(booking.voucher_amount ?? 0) > 0;
    const open = codeOpen || hasPromo || hasVoucher;
    return (
      <div className="mb-3">
        {!open ? (
          <button type="button" className="btn btn-link p-0" onClick={() => this.setState({ codeOpen: true })} disabled={disabled}>
            <i className="bi bi-tag me-1" aria-hidden="true" />
            {t('promo.toggle')}
          </button>
        ) : (
          <div className="border rounded p-3 bg-light">
            <form onSubmit={this.applyCode}>
              <label htmlFor="promo-code" className="form-label small fw-semibold">
                <i className="bi bi-tag me-1" aria-hidden="true" />
                {t('promo.label')}
              </label>
              <div className="input-group">
                <input
                  id="promo-code"
                  className="form-control text-uppercase"
                  placeholder={t('promo.placeholder')}
                  value={code}
                  maxLength={40}
                  autoComplete="off"
                  disabled={disabled || codeBusy}
                  onChange={(e) => this.setState({ code: e.target.value })}
                />
                <button type="submit" className="btn btn-primary" disabled={disabled || codeBusy || !code.trim()}>
                  {codeBusy ? t('promo.applying') : t('promo.apply')}
                </button>
              </div>
            </form>
            {(hasPromo || hasVoucher) && (
              <div className="d-flex flex-wrap gap-2 mt-2">
                {hasPromo && (
                  <span className="badge bg-success d-inline-flex align-items-center gap-1">
                    <i className="bi bi-tag-fill" aria-hidden="true" />
                    {booking.promo_code_text}
                    <button type="button" className="btn btn-sm btn-link text-white p-0 ms-1" title={t('promo.remove')} aria-label={t('promo.remove')}
                      onClick={() => this.removeCode('promo')} disabled={disabled || codeBusy}>
                      <i className="bi bi-x-circle" aria-hidden="true" />
                    </button>
                  </span>
                )}
                {hasVoucher && (
                  <span className="badge bg-success d-inline-flex align-items-center gap-1">
                    <i className="bi bi-gift-fill" aria-hidden="true" />
                    {booking.voucher_code ?? t('promo.voucherFallback')}
                    <button type="button" className="btn btn-sm btn-link text-white p-0 ms-1" title={t('promo.remove')} aria-label={t('promo.remove')}
                      onClick={() => this.removeCode('voucher')} disabled={disabled || codeBusy}>
                      <i className="bi bi-x-circle" aria-hidden="true" />
                    </button>
                  </span>
                )}
              </div>
            )}
            {codeError && <div className="text-danger small mt-2">{codeError}</div>}
            {codeInfo && <div className="text-success small mt-2">{codeInfo}</div>}
            <div className="text-muted small mt-1">{t('promo.hint')}</div>
          </div>
        )}
      </div>
    );
  }

  private renderCodeLines(booking: PromoBooking): React.ReactNode {
    const { t } = this.props.i18n;
    const promo = Number(booking.promo_discount ?? 0);
    const voucher = Number(booking.voucher_amount ?? 0);
    if (promo <= 0 && voucher <= 0) return null;
    return (
      <div className="pt-2">
        {promo > 0 && (
          <div className="d-flex justify-content-between py-1 text-success">
            <span><i className="bi bi-tag-fill me-1" aria-hidden="true" />{t('promo.promoLine', { code: booking.promo_code_text ?? '' })}</span>
            <span>−{formatINR(promo)}</span>
          </div>
        )}
        {voucher > 0 && (
          <div className="d-flex justify-content-between py-1 text-success">
            <span><i className="bi bi-gift-fill me-1" aria-hidden="true" />{t('promo.voucherLine', { code: booking.voucher_code ?? '' })}</span>
            <span>−{formatINR(voucher)}</span>
          </div>
        )}
      </div>
    );
  }

  private cancel = async (): Promise<void> => {
    await api.post(`/bookings/${this.reference}/cancel/`);
    this.props.router.navigate('/my-bookings');
  };

  public render(): React.ReactNode {
    const { booking, config, method, error, info, paying, secondsLeft } = this.state;
    const live = config?.provider === 'razorpay';
    const { t } = this.props.i18n;

    if (booking === undefined) return <Loader />;
    if (booking === null) return <div className="container page py-4 py-lg-5"><Empty title={t('booking.notFound')} /></div>;

    const expired = booking.hold_expires_at !== null && secondsLeft === 0;

    return (
      <div className="container page py-4 py-lg-5">
        <h1 className="display-6 mb-4">{t('booking.checkout.title')}</h1>
        <div className="row g-4">
          <div className="col-lg-7">
            <div className="card border-0 shadow-sm">
              <div className="card-body p-4">
                {expired ? (
                  <div className="alert alert-danger">
                    {t('booking.checkout.expired')} <Link to={`/museums/${booking.museum_slug}`} className="alert-link">{t('booking.checkout.bookAgain')}</Link>
                  </div>
                ) : (
                  <div className="alert alert-info d-flex align-items-center gap-2">
                    <i className="bi bi-hourglass-split" aria-hidden="true" />
                    {booking.pay_by ? (
                      // Approved group request: seats are held for days, not minutes.
                      <span>
                        {t('booking.checkout.heldUntil.before')} <strong>{formatDateTime(booking.pay_by)}</strong>
                        {t('booking.checkout.heldUntil.after')}
                      </span>
                    ) : (
                      <span>
                        {t('booking.checkout.heldFor.before')}{' '}
                        <strong>
                          {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, '0')}
                        </strong>{' '}
                        {t('booking.checkout.heldFor.after')}
                      </span>
                    )}
                  </div>
                )}
                {error && <div className="alert alert-danger">{error}</div>}
                {info && <div className="alert alert-info">{info}</div>}
                {live ? (
                  <div className="mb-4">
                    <h3 className="h4 mb-2">{t('booking.checkout.securePayment')}</h3>
                    <p className="text-muted mb-2">
                      {t('booking.checkout.razorpayIntro')}
                    </p>
                    <div className="d-flex flex-wrap gap-2 small">
                      <span className="badge bg-light text-dark"><i className="bi bi-shield-lock-fill me-1 text-success" aria-hidden="true" />{t('booking.checkout.encrypted')}</span>
                      <span className="badge bg-light text-dark"><i className="bi bi-phone me-1" aria-hidden="true" />UPI</span>
                      <span className="badge bg-light text-dark"><i className="bi bi-credit-card me-1" aria-hidden="true" />{t('booking.checkout.cards')}</span>
                      <span className="badge bg-light text-dark"><i className="bi bi-bank me-1" aria-hidden="true" />{t('booking.method.netbanking')}</span>
                      {config?.test_mode && <span className="badge bg-warning">{t('booking.checkout.testMode')}</span>}
                    </div>
                  </div>
                ) : (
                <>
                <h3 className="h4 mb-3">{t('booking.checkout.paymentMethod')}</h3>
                <div className="list-group mb-4">
                  {METHODS.map((m) => (
                    <label key={m} className={`list-group-item list-group-item-action d-flex gap-3 align-items-center py-3 ${method === m ? 'active' : ''}`}>
                      <input className="form-check-input flex-shrink-0 mt-0" type="radio" name="method" value={m} checked={method === m} onChange={() => this.setState({ method: m })} />
                      <span>
                        <strong className="d-block">{t(`booking.method.${m}`)}</strong>
                        <small className={method === m ? '' : 'text-muted'}>{t(`booking.method.${m}.hint`)}</small>
                      </span>
                    </label>
                  ))}
                </div>
                </>
                )}
                {this.renderAddOns(booking, paying || expired)}
                {this.renderCodeBox(booking, paying || expired)}
                <button className="btn btn-accent btn-lg w-100" onClick={this.pay} disabled={paying || expired || !config || this.state.codeBusy || this.state.addonsBusy || this.addonsDirty()}>
                  <i className="bi bi-lock-fill me-2" aria-hidden="true" />
                  {paying ? t('booking.checkout.processing') : t('booking.checkout.pay', { amount: formatINR(booking.total_amount) })}
                </button>
                <p className="text-muted small mt-3 mb-2">
                  {live
                    ? t('booking.checkout.razorpayNote')
                    : t('booking.checkout.demoNote')}
                  {config && ` ${t('booking.checkout.refundPolicy', { hours: config.refund_full_before_hours })}`}
                </p>
                <button className="btn btn-link btn-sm text-danger p-0" onClick={this.cancel} disabled={paying}>
                  {t('booking.cancelBooking')}
                </button>
              </div>
            </div>
          </div>

          <div className="col-lg-5">
            <div className="card border-0 shadow-sm">
              <div className="card-body p-4">
                <div className="d-flex justify-content-between align-items-center">
                  <span className="ref">{booking.reference}</span>
                  <StatusBadge status={booking.status} />
                </div>
                {booking.is_group && (
                  <div className="d-flex flex-wrap align-items-center gap-2 mt-3">
                    <span className="badge bg-accent">
                      <i className="bi bi-people-fill me-1" aria-hidden="true" />
                      {t('booking.group')}
                    </span>
                    {booking.group_type_label && <span className="badge bg-light text-dark">{booking.group_type ? t(`common.groupType.${booking.group_type}`) : booking.group_type_label}</span>}
                  </div>
                )}
                <h3 className={`h4 ${booking.is_group ? 'mt-2' : 'mt-3'} mb-1`}>{booking.museum_name}</h3>
                <p className="text-muted small">
                  <i className="bi bi-geo-alt-fill me-1" aria-hidden="true" />
                  {placeLocation(booking.city_name, booking.state_name)}
                </p>
                <p>
                  <i className="bi bi-calendar-event me-2" aria-hidden="true" />
                  <strong>{formatDate(booking.visit_date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</strong>
                  <br />
                  <i className="bi bi-clock me-2" aria-hidden="true" />
                  {formatTime(booking.slot_start)} – {formatTime(booking.slot_end)}
                  {booking.is_group && (
                    <>
                      <br />
                      <i className="bi bi-people me-2" aria-hidden="true" />
                      {booking.organisation_name && <><strong>{booking.organisation_name}</strong> · </>}
                      {groupHeadcount(booking, t)}
                    </>
                  )}
                </p>
                {booking.items.map((i) => (
                  <div key={i.ticket_name} className="d-flex justify-content-between align-items-center py-2 border-bottom">
                    <span>{i.quantity} × {i.ticket_name}</span>
                    <span>{formatINR(i.line_total)}</span>
                  </div>
                ))}
                {booking.is_group && <GroupPriceLines booking={booking} />}
                {this.renderExtraLines(booking)}
                {this.renderCodeLines(booking)}
                <div className="d-flex justify-content-between fs-5 fw-bold mt-3">
                  <span>{Number((booking as PromoBooking).promo_discount ?? 0) + Number((booking as PromoBooking).voucher_amount ?? 0) > 0 ? t('promo.toPay') : t('booking.total')}</span>
                  <span className="text-end">{formatINR(booking.total_amount)}<FxHint amount={booking.total_amount} className="d-block fs-6 fw-normal" /></span>
                </div>
              </div>
            </div>
            {!booking.is_group && !booking.membership_card && (
              <p className="small text-muted mt-3 mb-0">
                <i className="bi bi-award me-1 text-accent" aria-hidden="true" />
                {t('shop.member.checkoutHint')} <Link to="/membership">{t('shop.member.checkoutLink')}</Link>
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }
}

export default withRouter(withI18n(Checkout));
