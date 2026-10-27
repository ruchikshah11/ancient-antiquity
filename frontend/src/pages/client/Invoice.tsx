import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import type { InvoiceWithExtras as InvoiceData } from '../../api/addons';
import { Empty, Loader } from '../../components/Common';
import { formatDate, formatTime } from '../../utils/format';
import { withI18n, WithI18nProps } from '../../i18n';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

/** Invoices show paise, unlike the rest of the site which rounds to whole rupees. */
const money = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const rs = (v: number | string | null | undefined): string => money.format(Number(v ?? 0));
const pct = (v: number | string): string => `${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}%`;

/** In Hindi the document labels (booking.invoice.doc.*) read bilingually, e.g. "Tax invoice / कर चालान". */
type InvoiceProps = WithRouterProps & WithI18nProps;

interface InvoiceState {
  invoice: InvoiceData | null | undefined;
  error: string;
}

class InvoicePage extends React.Component<InvoiceProps, InvoiceState> {
  public state: InvoiceState = { invoice: undefined, error: '' };

  private mounted = false;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentDidUpdate(prevProps: InvoiceProps): void {
    if (prevProps.router.params.reference !== this.props.router.params.reference) this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private load(): void {
    const id = ++this.requestId;
    const alive = (): boolean => this.mounted && id === this.requestId;
    this.setState({ invoice: undefined, error: '' });
    api
      .get<InvoiceData>(`/bookings/${this.props.router.params.reference}/invoice/`)
      .then((r) => alive() && this.setState({ invoice: r.data }))
      .catch((err) => alive() && this.setState({ invoice: null, error: errorMessage(err, this.props.i18n.t('booking.invoice.notFound')) }));
  }

  public render(): React.ReactNode {
    const { invoice, error } = this.state;
    const reference = this.props.router.params.reference ?? '';
    const { t } = this.props.i18n;
    if (invoice === undefined) return <Loader />;
    if (invoice === null) {
      return (
        <div className="container py-5">
          <Empty title={t('booking.invoice.notAvailable')}>
            <p>{error}</p>
            <Link to={`/tickets/${reference}`} className="btn btn-primary">{t('booking.invoice.back')}</Link>
          </Empty>
        </div>
      );
    }

    const { seller, buyer, place, payment } = invoice;
    return (
      <div className="container py-4" style={{ maxWidth: 900 }}>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3 no-print">
          <Link to={`/tickets/${invoice.reference}`} className="btn btn-link px-0">
            <i className="bi bi-arrow-left me-1" aria-hidden="true" />{t('booking.invoice.back')}
          </Link>
          <button type="button" className="btn btn-accent" onClick={() => window.print()}>
            <i className="bi bi-printer me-1" aria-hidden="true" />{t('booking.invoice.print')}
          </button>
        </div>

        <div className="card border-0 shadow-sm">
          <div className="card-body p-4 p-md-5">
            <div className="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-4">
              <div>
                <h1 className="h3 mb-1">{t('booking.invoice.doc.title')}</h1>
                <div className="text-muted small">{t('booking.invoice.doc.number')} <strong className="text-body">{invoice.invoice_number}</strong></div>
                <div className="text-muted small">{t('booking.invoice.doc.date')} {formatDate(invoice.invoice_date)}</div>
              </div>
              <div className="text-md-end small">
                <div className="fw-semibold">{seller.name}</div>
                <div style={{ whiteSpace: 'pre-line' }}>{seller.address}</div>
                <div>GSTIN: {seller.gstin || <span className="text-muted">{t('booking.invoice.doc.noGstin')}</span>}</div>
                {seller.email && <div>{seller.email}</div>}
              </div>
            </div>

            <div className="row g-4 mb-4 small">
              <div className="col-md-6">
                <div className="text-uppercase text-muted fw-semibold mb-1" style={{ fontSize: '0.75rem' }}>{t('booking.invoice.doc.billedTo')}</div>
                {buyer.organisation && <div className="fw-semibold">{buyer.organisation}{buyer.group_type ? ` (${buyer.group_type})` : ''}</div>}
                <div className={buyer.organisation ? '' : 'fw-semibold'}>{buyer.name}</div>
                {buyer.email && <div>{buyer.email}</div>}
                {buyer.phone && <div>{buyer.phone}</div>}
              </div>
              <div className="col-md-6">
                <div className="text-uppercase text-muted fw-semibold mb-1" style={{ fontSize: '0.75rem' }}>{t('booking.invoice.doc.visit')}</div>
                <div className="fw-semibold">{place.name}</div>
                <div>{place.address}</div>
                <div>{place.city}, {place.state}</div>
                <div>
                  {formatDate(invoice.visit_date)} · {formatTime(invoice.slot_start)}–{formatTime(invoice.slot_end)} · {t(invoice.total_visitors === 1 ? 'common.group.visitors.one' : 'common.group.visitors.other', { n: invoice.total_visitors })}
                </div>
                <div>{t('booking.invoice.doc.reference')} <span className="ref">{invoice.reference}</span></div>
                <div>{t('booking.invoice.doc.placeOfSupply')}: {invoice.place_of_supply}</div>
              </div>
            </div>

            <div className="table-responsive">
              <table className="table align-middle">
                <thead className="table-light">
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">{t('booking.invoice.doc.description')}</th>
                    <th scope="col" className="text-end">{t('booking.invoice.doc.qty')}</th>
                    <th scope="col" className="text-end">{t('booking.invoice.doc.rate')}</th>
                    <th scope="col" className="text-end">{t('booking.invoice.doc.amount')}</th>
                  </tr>
                </thead>
                <tbody>
                  {invoice.items.map((item, i) => (
                    <tr key={`${item.description}-${i}`}>
                      <td>{i + 1}</td>
                      <td>{item.kind === 'addon' ? t('shop.invoice.addon') : t('booking.invoice.doc.entryTicket')}: {item.description}</td>
                      <td className="text-end">{item.quantity}</td>
                      <td className="text-end">{rs(item.unit_price)}</td>
                      <td className="text-end">{rs(item.amount)}</td>
                    </tr>
                  ))}
                </tbody>
                <tbody className="border-top-0">
                  <tr>
                    <td colSpan={4} className="text-end">{t('booking.invoice.doc.subtotal')}</td>
                    <td className="text-end">{rs(invoice.subtotal)}</td>
                  </tr>
                  {/* Older invoices only have the combined `discount`; newer ones split it by kind. */}
                  {Number(invoice.group_discount ?? invoice.discount) > 0 && (
                    <tr>
                      <td colSpan={4} className="text-end">{t('booking.invoice.doc.groupDiscount')}</td>
                      <td className="text-end">− {rs(invoice.group_discount ?? invoice.discount)}</td>
                    </tr>
                  )}
                  {Number(invoice.membership_discount ?? 0) > 0 && (
                    <tr>
                      <td colSpan={4} className="text-end">
                        {t('shop.invoice.memberDiscount', { card: invoice.membership_card ?? '' })}
                      </td>
                      <td className="text-end">− {rs(invoice.membership_discount ?? 0)}</td>
                    </tr>
                  )}
                  {Number(invoice.promo_discount ?? 0) > 0 && (
                    <tr>
                      <td colSpan={4} className="text-end">
                        {t('booking.invoice.doc.promoDiscount', { code: invoice.promo_code ?? '' })}
                      </td>
                      <td className="text-end">− {rs(invoice.promo_discount ?? 0)}</td>
                    </tr>
                  )}
                  <tr className="fw-semibold">
                    <td colSpan={4} className="text-end">{t('booking.invoice.doc.totalPaid')}</td>
                    <td className="text-end">{rs(invoice.total)}</td>
                  </tr>
                  {Number(invoice.voucher_amount ?? 0) > 0 && (
                    <>
                      <tr className="small text-muted">
                        <td colSpan={4} className="text-end">{t('booking.invoice.doc.paidByVoucher')}</td>
                        <td className="text-end">{rs(invoice.voucher_amount ?? 0)}</td>
                      </tr>
                      <tr className="small text-muted">
                        <td colSpan={4} className="text-end">{t('booking.invoice.doc.paidOnline')}</td>
                        <td className="text-end">{rs(invoice.paid_online ?? 0)}</td>
                      </tr>
                    </>
                  )}
                </tbody>
              </table>
            </div>

            <div className="row g-4 small">
              <div className="col-md-6">
                <div className="text-uppercase text-muted fw-semibold mb-1" style={{ fontSize: '0.75rem' }}>{t('booking.invoice.doc.payment')}</div>
                <div>{t('booking.invoice.doc.status')}: {invoice.status_label}</div>
                <div>{t('booking.invoice.doc.channel')}: {payment.channel}</div>
                {payment.method && <div>{t('booking.invoice.doc.method')}: {payment.method}</div>}
                {payment.payment_id && <div>{t('booking.paymentId')}: <span className="ref">{payment.payment_id}</span></div>}
                {payment.paid_at && <div>{t('booking.invoice.doc.paidOn')} {formatDate(payment.paid_at)}</div>}
              </div>
              <div className="col-md-6">
                <table className="table table-sm mb-0">
                  <caption className="visually-hidden">{t('booking.invoice.doc.taxBreakup')}</caption>
                  <tbody>
                    <tr><th scope="row" className="fw-normal">{t('booking.invoice.doc.taxableValue')}</th><td className="text-end">{rs(invoice.taxable_value)}</td></tr>
                    <tr><th scope="row" className="fw-normal">CGST @ {pct(invoice.cgst_percent)}</th><td className="text-end">{rs(invoice.cgst)}</td></tr>
                    <tr><th scope="row" className="fw-normal">SGST @ {pct(invoice.sgst_percent)}</th><td className="text-end">{rs(invoice.sgst)}</td></tr>
                    <tr className="fw-semibold"><th scope="row">{t('booking.invoice.doc.invoiceTotal')}</th><td className="text-end">{rs(invoice.total)}</td></tr>
                  </tbody>
                </table>
              </div>
            </div>

            <hr className="my-4" />
            <ul className="list-unstyled text-muted small mb-0">
              {invoice.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          </div>
        </div>
      </div>
    );
  }
}

export default withRouter(withI18n(InvoicePage));
