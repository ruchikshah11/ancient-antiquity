import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import { PAN_PATTERN, receiptPath } from '../../api/donations';
import type { Donation, DonationInfo } from '../../api/donations';
import { openRazorpay, RazorpayOrder } from '../../api/razorpay';
import type { Museum } from '../../api/types';
import { Loader } from '../../components/Common';
import FxHint from '../../components/FxHint';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatINR } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

/*
 * /donate?museum=<slug>: a gift to one place or to the general heritage fund. Guests can give; signed-in visitors
 * get their details prefilled. Pay right here (Razorpay when configured, otherwise the demo gateway), then go to
 * the printable receipt (/donations/<reference>?token=...).
 */

const METHODS = ['upi', 'card', 'netbanking'];
const BRAND_COLOR = '#0277bd'; // matches $primary in theme.scss
const DEFAULT_PRESETS = [500, 1000, 2500, 5000];
const MIN_AMOUNT = 100;

interface Donor {
  name: string;
  email: string;
  phone: string;
  pan: string;
  address: string;
}

type DonateProps = WithRouterProps & WithAuthProps & WithI18nProps;

interface DonateState {
  info: DonationInfo | null;
  place: Pick<Museum, 'slug' | 'name' | 'city_name'> | null;
  toPlace: boolean;
  preset: number | null;
  custom: string;
  donor: Donor;
  wants80g: boolean;
  method: string;
  /** Created but not yet paid (kept so a closed payment window can be retried). */
  donation: Donation | null;
  busy: boolean;
  error: string;
  notice: string;
}

class Donate extends React.Component<DonateProps, DonateState> {
  public state: DonateState = {
    info: null,
    place: null,
    toPlace: true,
    preset: 1000,
    custom: '',
    donor: this.donorFromUser(),
    wants80g: true,
    method: 'upi',
    donation: null,
    busy: false,
    error: '',
    notice: '',
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    api
      .get<DonationInfo>('/donations/info/')
      .then(({ data }) => this.mounted && this.setState({ info: data }))
      .catch(() => this.mounted && this.setState({
        info: { trust: { name: '', pan: '', registration_80g: '' }, min_amount: String(MIN_AMOUNT), presets: DEFAULT_PRESETS, provider: 'mock' },
      }));
    this.loadPlace();
  }

  public componentDidUpdate(prevProps: DonateProps): void {
    if (prevProps.router.searchParams.get('museum') !== this.props.router.searchParams.get('museum')) this.loadPlace();
    if (prevProps.auth.user !== this.props.auth.user && this.props.auth.user) {
      const { donor } = this.state;
      if (!donor.name && !donor.email) this.setState({ donor: { ...this.donorFromUser(), pan: donor.pan, address: donor.address } });
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private donorFromUser(): Donor {
    const u = this.props.auth.user;
    return {
      name: u ? `${u.first_name} ${u.last_name}`.trim() : '',
      email: u?.email ?? '',
      phone: u?.phone ?? '',
      pan: '',
      address: '',
    };
  }

  private loadPlace(): void {
    const slug = this.props.router.searchParams.get('museum');
    if (!slug) {
      this.setState({ place: null });
      return;
    }
    cachedGet<Museum>(`/museums/${slug}/`, undefined, (data) => {
      if (this.mounted) this.setState({ place: { slug: data.slug, name: data.name, city_name: data.city_name }, toPlace: true });
    }).catch(() => this.mounted && this.setState({ place: null }));
  }

  private amount(): number {
    const { preset, custom } = this.state;
    return preset ?? Math.floor(Number(custom) || 0);
  }

  /** Any change to the form starts a fresh donation (an unpaid one is simply left pending). */
  private edit(patch: Partial<DonateState>): void {
    this.setState({ ...patch, donation: null, error: '', notice: '' } as DonateState);
  }

  private setDonor = (k: keyof Donor) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>): void => {
    const value = k === 'pan' ? e.target.value.toUpperCase().replace(/\s/g, '') : e.target.value;
    this.edit({ donor: { ...this.state.donor, [k]: value } });
  };

  private validate(): string {
    const { t } = this.props.i18n;
    const { donor, wants80g } = this.state;
    const min = Number(this.state.info?.min_amount ?? MIN_AMOUNT);
    if (this.amount() < min) return t('giving.donate.errMin', { amount: formatINR(min) });
    if (!donor.name.trim() || !donor.email.trim()) return t('giving.donate.errDonor');
    if (donor.pan && !PAN_PATTERN.test(donor.pan)) return t('giving.donate.errPan');
    if (wants80g && (!donor.pan || !donor.address.trim())) return t('giving.donate.err80g');
    return '';
  }

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const problem = this.validate();
    if (problem) {
      this.setState({ error: problem });
      return;
    }
    const { t } = this.props.i18n;
    const { donor, wants80g, place, toPlace, method } = this.state;
    this.setState({ busy: true, error: '', notice: '' });
    try {
      let donation = this.state.donation;
      if (!donation) {
        ({ data: donation } = await api.post<Donation>('/donations/', {
          amount: this.amount(),
          museum: place && toPlace ? place.slug : null,
          donor_name: donor.name.trim(),
          donor_email: donor.email.trim(),
          donor_phone: donor.phone.trim(),
          donor_pan: donor.pan,
          donor_address: donor.address.trim(),
          wants_80g: wants80g,
        }));
        if (this.mounted) this.setState({ donation });
      }
      const token = { token: donation.access_token };
      const { data: rz } = await api.post<RazorpayOrder | { provider: 'mock' }>(`/donations/${donation.reference}/payment-order/`, token);
      let paid: Donation;
      if (rz.provider === 'razorpay') {
        let result;
        try {
          result = await openRazorpay(rz, BRAND_COLOR);
        } catch (err) {
          api.post(`/donations/${donation.reference}/failed/`, token).catch(() => undefined);
          throw err;
        }
        if (!result) {
          if (this.mounted) this.setState({ busy: false, notice: t('giving.donate.windowClosed') });
          return;
        }
        if (this.mounted) this.setState({ notice: t('giving.donate.confirming') });
        ({ data: paid } = await api.post<Donation>(`/donations/${donation.reference}/pay/`, { ...result, ...token }));
      } else {
        await new Promise((r) => setTimeout(r, 600));
        ({ data: paid } = await api.post<Donation>(`/donations/${donation.reference}/pay/`, { method, ...token }));
      }
      if (this.mounted) this.props.router.navigate(receiptPath(paid));
    } catch (err) {
      const message = err instanceof Error && !('isAxiosError' in err) ? err.message : errorMessage(err);
      if (this.mounted) this.setState({ error: message, busy: false, notice: '' });
    }
  };

  private renderAmount(): React.ReactNode {
    const { t } = this.props.i18n;
    const { info, preset, custom } = this.state;
    const presets = info?.presets?.length ? info.presets : DEFAULT_PRESETS;
    const min = Number(info?.min_amount ?? MIN_AMOUNT);
    return (
      <fieldset className="mb-4">
        <legend className="h6">{t('giving.donate.amount')}</legend>
        <div className="row g-2 mb-2">
          {presets.map((p) => (
            <div className="col-6 col-sm-3" key={p}>
              <button
                type="button"
                className={`btn w-100 donate-preset ${preset === p ? 'btn-primary' : 'btn-outline-primary'}`}
                aria-pressed={preset === p}
                onClick={() => this.edit({ preset: p, custom: '' })}
              >
                {formatINR(p)}
              </button>
            </div>
          ))}
        </div>
        <label htmlFor="d-custom" className="form-label small text-muted mb-1">{t('giving.donate.custom')}</label>
        <div className="input-group">
          <span className="input-group-text">₹</span>
          <input
            id="d-custom" type="number" inputMode="numeric" className="form-control" min={min} step={1}
            placeholder={t('giving.donate.customPlaceholder', { amount: formatINR(min) })}
            value={custom}
            onFocus={() => preset !== null && this.edit({ preset: null })}
            onChange={(e) => this.edit({ custom: e.target.value, preset: null })}
          />
        </div>
        <div className="form-text">{t('giving.donate.minNote', { amount: formatINR(min) })}</div>
      </fieldset>
    );
  }

  private renderDonor(): React.ReactNode {
    const { t } = this.props.i18n;
    const { donor, wants80g } = this.state;
    return (
      <fieldset className="mb-4">
        <legend className="h6">{t('giving.donate.yourDetails')}</legend>
        <div className="row g-2">
          <div className="col-12">
            <label htmlFor="d-name" className="form-label">{t('giving.donate.name')}</label>
            <input id="d-name" className="form-control" value={donor.name} onChange={this.setDonor('name')} autoComplete="name" required maxLength={120} />
          </div>
          <div className="col-sm-7">
            <label htmlFor="d-email" className="form-label">{t('giving.donate.email')}</label>
            <input id="d-email" type="email" className="form-control" value={donor.email} onChange={this.setDonor('email')} autoComplete="email" required />
          </div>
          <div className="col-sm-5">
            <label htmlFor="d-phone" className="form-label">{t('giving.donate.phone')}</label>
            <input id="d-phone" type="tel" className="form-control" value={donor.phone} onChange={this.setDonor('phone')} autoComplete="tel" maxLength={15} />
          </div>
        </div>
        <div className="form-check form-switch mt-3">
          <input id="d-80g" className="form-check-input" type="checkbox" checked={wants80g} onChange={(e) => this.edit({ wants80g: e.target.checked })} />
          <label htmlFor="d-80g" className="form-check-label">{t('giving.donate.want80g')}</label>
        </div>
        {wants80g && (
          <div className="row g-2 mt-1">
            <div className="col-sm-5">
              <label htmlFor="d-pan" className="form-label">{t('giving.donate.pan')}</label>
              <input
                id="d-pan" className="form-control text-uppercase" value={donor.pan} onChange={this.setDonor('pan')}
                maxLength={10} placeholder="ABCDE1234F" pattern="[A-Z]{5}[0-9]{4}[A-Z]" required aria-describedby="d-pan-help"
              />
              <div id="d-pan-help" className="form-text">{t('giving.donate.panHelp')}</div>
            </div>
            <div className="col-sm-7">
              <label htmlFor="d-address" className="form-label">{t('giving.donate.address')}</label>
              <textarea id="d-address" className="form-control" rows={2} value={donor.address} onChange={this.setDonor('address')} autoComplete="street-address" maxLength={300} required />
            </div>
          </div>
        )}
      </fieldset>
    );
  }

  private renderPayment(): React.ReactNode {
    const { t } = this.props.i18n;
    const { info, method } = this.state;
    if (info?.provider === 'razorpay') return <p className="text-muted small">{t('booking.checkout.razorpayIntro')}</p>;
    return (
      <fieldset className="mb-3">
        <legend className="h6">{t('giving.donate.payWith')}</legend>
        <div className="list-group">
          {METHODS.map((m) => (
            <label key={m} className={`list-group-item list-group-item-action d-flex gap-3 align-items-center py-2 ${method === m ? 'active' : ''}`}>
              <input className="form-check-input flex-shrink-0 mt-0" type="radio" name="donate-method" value={m} checked={method === m} onChange={() => this.setState({ method: m })} />
              <span>
                <strong className="d-block">{t(`booking.method.${m}`)}</strong>
                <small className={method === m ? '' : 'text-muted'}>{t(`booking.method.${m}.hint`)}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { info, place, toPlace, busy, error, notice, wants80g } = this.state;
    if (!info) return <Loader />;
    const amount = this.amount();
    const trustName = info.trust.name || t('giving.donate.trustFallback');
    return (
      <div className="container page py-4 py-lg-5">
        <div className="row g-4">
          <div className="col-lg-5">
            <div className="donate-hero rounded-3 p-4 mb-4 text-white">
              <i className="bi bi-heart-fill fs-2 text-accent" aria-hidden="true" />
              <h1 className="h2 mt-2">{t('giving.donate.title')}</h1>
              <p className="mb-0">{t('giving.donate.lead')}</p>
            </div>
            <div className="card border-0 shadow-sm mb-3">
              <div className="card-body">
                <h2 className="h5"><i className="bi bi-receipt me-2 text-primary" aria-hidden="true" />{t('giving.donate.taxTitle')}</h2>
                <p className="small mb-2">{t('giving.donate.taxText', { trust: trustName })}</p>
                <ul className="small mb-0 ps-3">
                  <li>{t('giving.donate.tax1')}</li>
                  <li>{t('giving.donate.tax2')}</li>
                  <li>{t('giving.donate.tax3')}</li>
                </ul>
                {info.trust.registration_80g && (
                  <p className="small text-muted mt-2 mb-0">
                    {t('giving.receipt.reg80g')}: <span className="ref">{info.trust.registration_80g}</span>
                    {info.trust.pan && <> · PAN <span className="ref">{info.trust.pan}</span></>}
                  </p>
                )}
              </div>
            </div>
            <p className="small text-muted">
              <i className="bi bi-shield-check me-1" aria-hidden="true" />
              {t('giving.donate.secure')}
            </p>
          </div>

          <div className="col-lg-7">
            <form className="card border-0 shadow" onSubmit={this.submit} noValidate>
              <div className="card-body p-4">
                <fieldset className="mb-4">
                  <legend className="h6">{t('giving.donate.where')}</legend>
                  {place ? (
                    <>
                      <div className="form-check">
                        <input id="d-to-place" className="form-check-input" type="radio" name="d-where" checked={toPlace} onChange={() => this.edit({ toPlace: true })} />
                        <label htmlFor="d-to-place" className="form-check-label">
                          {t('giving.donate.toPlace', { name: place.name })}
                          {place.city_name && <span className="text-muted small"> · {place.city_name}</span>}
                        </label>
                      </div>
                      <div className="form-check">
                        <input id="d-to-fund" className="form-check-input" type="radio" name="d-where" checked={!toPlace} onChange={() => this.edit({ toPlace: false })} />
                        <label htmlFor="d-to-fund" className="form-check-label">{t('giving.donate.toFund')}</label>
                      </div>
                    </>
                  ) : (
                    <p className="mb-0">
                      <i className="bi bi-bank me-2 text-primary" aria-hidden="true" />
                      {t('giving.donate.toFund')}
                      <span className="d-block small text-muted">{t('giving.donate.fundHint')}</span>
                    </p>
                  )}
                </fieldset>

                {this.renderAmount()}
                {this.renderDonor()}
                {this.renderPayment()}

                {error && <div className="alert alert-danger" role="alert">{error}</div>}
                {notice && <div className="alert alert-info" role="status">{notice}</div>}

                <div className="d-flex justify-content-between align-items-baseline mb-3">
                  <span className="fw-semibold">{t('giving.donate.total')}</span>
                  <span className="text-end">
                    <span className="fs-4 fw-bold d-block">{formatINR(amount)}</span>
                    <FxHint amount={amount} />
                  </span>
                </div>
                <button className="btn btn-accent btn-lg w-100" disabled={busy || amount <= 0}>
                  <i className="bi bi-heart-fill me-2" aria-hidden="true" />
                  {busy ? t('booking.checkout.processing') : t('giving.donate.pay', { amount: formatINR(amount) })}
                </button>
                <p className="small text-muted mt-2 mb-0">
                  {info.provider === 'razorpay' ? t('booking.checkout.razorpayNote') : t('booking.checkout.demoNote')}
                </p>
                {wants80g && <p className="small text-muted mt-1 mb-0">{t('giving.donate.receiptNote')}</p>}
              </div>
            </form>
            {place && (
              <Link to={`/museums/${place.slug}`} className="btn btn-link px-0 mt-2">
                <i className="bi bi-arrow-left me-1" aria-hidden="true" />
                {t('giving.donate.backToPlace', { name: place.name })}
              </Link>
            )}
          </div>
        </div>
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(Donate)));
