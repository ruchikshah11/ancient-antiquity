import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import type { Donation } from '../../api/donations';
import { Empty, Loader } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

/*
 * /donations/:receipt?token=... : printable donation receipt (80G wording only when asked for and a PAN was given).
 * Opens for the donor's account (or same email), an admin, or anyone holding the signed link from the email.
 * Print styles follow the invoice page: the .no-print toolbar is hidden and the card prints flat.
 */

const money = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rs = (v: number | string | null | undefined): string => money.format(Number(v ?? 0));

type ReceiptProps = WithRouterProps & WithAuthProps & WithI18nProps;

interface ReceiptState {
  donation: Donation | null | undefined;
  error: string;
}

class DonationReceipt extends React.Component<ReceiptProps, ReceiptState> {
  public state: ReceiptState = { donation: undefined, error: '' };

  private mounted = false;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentDidUpdate(prevProps: ReceiptProps): void {
    if (prevProps.router.params.receipt !== this.props.router.params.receipt || prevProps.auth.user !== this.props.auth.user) this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private load(): void {
    const id = ++this.requestId;
    const alive = (): boolean => this.mounted && id === this.requestId;
    const token = this.props.router.searchParams.get('token') ?? undefined;
    this.setState({ donation: undefined, error: '' });
    api
      .get<Donation>(`/donations/${this.props.router.params.receipt}/`, { params: token ? { token } : undefined })
      .then((r) => alive() && this.setState({ donation: r.data }))
      .catch((err) => alive() && this.setState({ donation: null, error: errorMessage(err, this.props.i18n.t('giving.receipt.notFound')) }));
  }

  private methodLabel(method: string): string {
    const { t } = this.props.i18n;
    if (['upi', 'card', 'netbanking'].includes(method)) return t(`booking.method.${method}`);
    return method === 'wallet' ? t('giving.receipt.wallet') : '—';
  }

  private renderPending(d: Donation): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <div className="container py-5" style={{ maxWidth: 640 }}>
        <Empty title={t(`giving.receipt.status.${d.status}`)}>
          <p>{t('giving.receipt.notPaid')}</p>
          <Link to={d.museum_slug ? `/donate?museum=${d.museum_slug}` : '/donate'} className="btn btn-accent">{t('giving.receipt.tryAgain')}</Link>
        </Empty>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { donation: d, error } = this.state;
    if (d === undefined) return <Loader />;
    if (d === null) {
      return (
        <div className="container py-5">
          <Empty title={t('giving.receipt.notAvailable')}>
            <p>{error}</p>
            <p className="small text-muted">{t('giving.receipt.accessHint')}</p>
            <Link to="/donate" className="btn btn-primary">{t('giving.receipt.donateAgain')}</Link>
          </Empty>
        </div>
      );
    }
    if (d.status === 'pending' || d.status === 'failed') return this.renderPending(d);

    const trustName = d.trust.name || t('giving.donate.trustFallback');
    return (
      <div className="container py-4 donation-receipt" style={{ maxWidth: 860 }}>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3 no-print">
          <Link to={d.museum_slug ? `/museums/${d.museum_slug}` : '/'} className="btn btn-link px-0">
            <i className="bi bi-arrow-left me-1" aria-hidden="true" />{t('giving.receipt.back')}
          </Link>
          <button type="button" className="btn btn-accent" onClick={() => window.print()}>
            <i className="bi bi-printer me-1" aria-hidden="true" />{t('giving.receipt.print')}
          </button>
        </div>

        {d.status === 'paid' && (
          <div className="alert alert-success no-print" role="status">
            <i className="bi bi-heart-fill me-2" aria-hidden="true" />
            {t('giving.receipt.thanks', { name: d.donor_name })}
          </div>
        )}
        {d.status === 'refunded' && (
          <div className="alert alert-warning" role="status">{t('giving.receipt.refunded')}</div>
        )}

        <div className="card border-0 shadow-sm">
          <div className="card-body p-4 p-md-5">
            <div className="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-4 pb-3 border-bottom">
              <div>
                <div className="fw-bold fs-5">{trustName}</div>
                {d.trust.pan && <div className="small">PAN: <span className="ref">{d.trust.pan}</span></div>}
                {d.trust.registration_80g && <div className="small">{t('giving.receipt.reg80g')}: <span className="ref">{d.trust.registration_80g}</span></div>}
              </div>
              <div className="text-md-end">
                <h1 className="h3 mb-1">{t('giving.receipt.title')}</h1>
                <div className="small text-muted">{t('giving.receipt.number')} <strong className="text-body ref">{d.receipt_number}</strong></div>
                {d.paid_at && <div className="small text-muted">{t('giving.receipt.date')} {formatDate(d.paid_at)}</div>}
              </div>
            </div>

            <div className="row g-4 mb-4 small">
              <div className="col-md-6">
                <div className="text-uppercase text-muted fw-semibold mb-1" style={{ fontSize: '0.75rem' }}>{t('giving.receipt.receivedFrom')}</div>
                <div className="fw-semibold">{d.donor_name}</div>
                {d.donor_address && <div style={{ whiteSpace: 'pre-line' }}>{d.donor_address}</div>}
                {d.donor_pan && <div>{t('giving.receipt.donorPan')}: <span className="ref">{d.donor_pan}</span></div>}
                <div>{d.donor_email}</div>
                {d.donor_phone && <div>{d.donor_phone}</div>}
              </div>
              <div className="col-md-6">
                <div className="text-uppercase text-muted fw-semibold mb-1" style={{ fontSize: '0.75rem' }}>{t('giving.receipt.payment')}</div>
                <div>{t('giving.receipt.purpose')}: {d.museum_name ?? t('giving.donate.toFund')}</div>
                <div>{t('giving.receipt.mode')}: {this.methodLabel(d.payment_method)} ({t('giving.receipt.online')})</div>
                {d.payment_id && <div>{t('giving.receipt.paymentRef')}: <span className="ref">{d.payment_id}</span></div>}
                <div>{t('giving.receipt.donationRef')}: <span className="ref">{d.reference}</span></div>
              </div>
            </div>

            <div className="receipt-amount rounded-3 p-3 mb-4">
              <div className="d-flex justify-content-between align-items-baseline flex-wrap gap-2">
                <span className="fw-semibold">{t('giving.receipt.amount')}</span>
                <span className="fs-3 fw-bold">{rs(d.amount)}</span>
              </div>
              <div className="small">{t('giving.receipt.inWords')}: <strong>{d.amount_in_words}</strong></div>
            </div>

            {d.is_80g_eligible && d.status === 'paid' && (
              <p className="small border-start border-3 ps-3 receipt-80g">
                {t('giving.receipt.eligible80g', { trust: trustName, reg: d.trust.registration_80g || '—' })}
              </p>
            )}

            <hr className="my-4" />
            <ul className="list-unstyled text-muted small mb-0">
              <li>{t('giving.receipt.note1')}</li>
              {d.is_80g_eligible && <li>{t('giving.receipt.note10be')}</li>}
              <li>{t('giving.receipt.note2')}</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(DonationReceipt)));
