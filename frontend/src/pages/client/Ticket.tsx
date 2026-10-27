import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { resendTicketEmail } from '../../api/notifications';
import type { Booking } from '../../api/types';
import { Empty, Loader, StatusBadge } from '../../components/Common';
import { GroupPriceLines, groupHeadcount } from '../../components/GroupSummary';
import { formatDate, formatDateTime, formatINR, formatTime } from '../../utils/format';
import { withI18n, WithI18nProps } from '../../i18n';
import ReminderSettings from '../../components/ReminderSettings';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

type TicketProps = WithRouterProps & WithI18nProps;

interface TicketState {
  booking: Booking | null | undefined;
  error: string;
  emailing: boolean;
  emailNotice: { ok: boolean; text: string } | null;
}

class Ticket extends React.Component<TicketProps, TicketState> {
  public state: TicketState = { booking: undefined, error: '', emailing: false, emailNotice: null };

  private mounted = false;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentDidUpdate(prevProps: TicketProps): void {
    if (prevProps.router.params.reference !== this.props.router.params.reference) this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private load(): void {
    const id = ++this.requestId;
    const alive = (): boolean => this.mounted && id === this.requestId;
    api
      .get<Booking>(`/bookings/${this.props.router.params.reference}/`)
      .then((r) => alive() && this.setState({ booking: r.data }))
      .catch(() => alive() && this.setState({ booking: null }));
  }

  private cancel = async (): Promise<void> => {
    const { t } = this.props.i18n;
    const b = this.state.booking;
    const refund = Number(b?.refundable_amount ?? 0);
    const paid = Number(b?.total_amount ?? 0);
    const terms =
      paid <= 0 || b?.status === 'pending'
        ? t('booking.ticket.confirmCancel')
        : refund > 0
          ? t('booking.ticket.confirmCancelRefund', { amount: formatINR(refund) })
          : t('booking.ticket.confirmCancelNoRefund');
    if (!confirm(`${terms}\n\n${t('booking.ticket.cannotUndo')}`)) return;
    try {
      const { data } = await api.post<Booking>(`/bookings/${this.props.router.params.reference}/cancel/`);
      if (this.mounted) this.setState({ booking: data });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    }
  };

  private emailTicket = async (): Promise<void> => {
    const reference = this.state.booking?.reference;
    if (!reference) return;
    this.setState({ emailing: true, emailNotice: null });
    try {
      const { detail } = await resendTicketEmail(reference);
      if (this.mounted) this.setState({ emailNotice: { ok: true, text: detail } });
    } catch (err) {
      if (this.mounted) this.setState({ emailNotice: { ok: false, text: errorMessage(err, this.props.i18n.t('booking.ticket.emailFailed')) } });
    } finally {
      if (this.mounted) this.setState({ emailing: false });
    }
  };

  public render(): React.ReactNode {
    const { booking, error, emailing, emailNotice } = this.state;
    const { t } = this.props.i18n;

    if (booking === undefined) return <Loader />;
    if (booking === null) return <div className="container page py-4 py-lg-5"><Empty title={t('booking.ticket.notFound')} /></div>;

    const valid = booking.status === 'confirmed' || booking.status === 'checked_in';

    return (
      <div className="container page py-4 py-lg-5" style={{ maxWidth: 880 }}>
        {booking.status === 'confirmed' && (
          <div className="alert alert-success d-flex align-items-center gap-2 no-print">
            <i className="bi bi-check-circle-fill" aria-hidden="true" />
            <span>{t('booking.ticket.confirmed')}</span>
          </div>
        )}
        {error && <div className="alert alert-danger">{error}</div>}

        <div className="card border-0 shadow e-ticket">
          <div className="card-body p-4">
            <div className="d-flex justify-content-between align-items-center">
              <span className="text-muted small fw-semibold">ANCIENT ANTIQUITY · {t('booking.ticket.eTicket')}</span>
              <StatusBadge status={booking.status} />
            </div>
            {booking.is_group && (
              <div className="d-flex flex-wrap align-items-center gap-2 mt-3">
                <span className="badge bg-accent">
                  <i className="bi bi-people-fill me-1" aria-hidden="true" />
                  {t('booking.group')}
                </span>
                {booking.group_type_label && <span className="badge bg-light text-dark">{booking.group_type ? t(`common.groupType.${booking.group_type}`) : booking.group_type_label}</span>}
                {booking.organisation_name && <strong>{booking.organisation_name}</strong>}
              </div>
            )}
            <h2 className={`${booking.is_group ? 'mt-2' : 'mt-3'} mb-1`}>{booking.museum_name}</h2>
            <p className="text-muted">
              <i className="bi bi-geo-alt-fill me-1" aria-hidden="true" />
              {booking.museum_address}
            </p>
            <div className="row g-2 mb-3">
              <div className="col-6">
                <div className="fact">
                  <span className="label"><i className="bi bi-calendar-event me-1" aria-hidden="true" />{t('booking.date')}</span>
                  <strong>{formatDate(booking.visit_date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}</strong>
                </div>
              </div>
              <div className="col-6">
                <div className="fact">
                  <span className="label"><i className="bi bi-clock me-1" aria-hidden="true" />{t('booking.entrySlot')}</span>
                  <strong>{formatTime(booking.slot_start)} – {formatTime(booking.slot_end)}</strong>
                </div>
              </div>
              <div className="col-6">
                <div className="fact">
                  <span className="label"><i className="bi bi-people me-1" aria-hidden="true" />{t('booking.visitors')}</span>
                  <strong>{booking.is_group ? groupHeadcount(booking, t) : booking.total_visitors}</strong>
                </div>
              </div>
              <div className="col-6">
                <div className="fact">
                  <span className="label"><i className="bi bi-person me-1" aria-hidden="true" />{booking.is_group ? t('booking.groupLeader') : t('booking.leadVisitor')}</span>
                  <strong>{booking.visitor_name}</strong>
                </div>
              </div>
            </div>
            {booking.items.map((i) => (
              <div key={i.ticket_name} className="d-flex justify-content-between align-items-center py-2 border-bottom">
                <span>{i.quantity} × {i.ticket_name}</span>
                <span>{formatINR(i.line_total)}</span>
              </div>
            ))}
            {booking.is_group && <GroupPriceLines booking={booking} />}
            {Number(booking.membership_discount ?? 0) > 0 && (
              <div className="d-flex justify-content-between py-2 border-bottom text-success">
                <span>
                  <i className="bi bi-award-fill me-1" aria-hidden="true" />
                  {t('shop.member.discountLine')}
                  {booking.membership_card && <span className="small text-muted ms-1">({booking.membership_card})</span>}
                </span>
                <span>−{formatINR(booking.membership_discount)}</span>
              </div>
            )}
            {(booking.addons ?? []).length > 0 && (
              <div className="ticket-addons mt-3">
                <div className="small text-muted fw-semibold text-uppercase mb-1">{t('shop.addons.heading')}</div>
                <ul className="list-unstyled mb-0">
                  {(booking.addons ?? []).map((a) => (
                    <li key={a.addon} className="d-flex justify-content-between align-items-center py-1">
                      <span><i className={`bi bi-${a.icon} me-2 text-accent`} aria-hidden="true" />{a.quantity} × {a.name}</span>
                      <span>{Number(a.line_total) > 0 ? formatINR(a.line_total) : t('shop.addons.free')}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {booking.is_group && (booking.status === 'checked_in' || booking.visitors_arrived > 0) && (
              <div className="alert alert-info d-flex align-items-center gap-2 py-2 mt-3 mb-0">
                <i className="bi bi-door-open" aria-hidden="true" />
                <span>
                  {t('booking.ticket.entered')} <strong>{t('booking.ticket.enteredOf', { n: booking.visitors_arrived, total: booking.total_visitors })}</strong>
                  {booking.remaining_to_enter > 0 && <> · {t('booking.ticket.stillToEnter', { n: booking.remaining_to_enter })}</>}
                </span>
              </div>
            )}
            <div className="d-flex justify-content-between fs-5 fw-bold my-3">
              <span>{t('booking.amountPaid')}</span>
              <span>{formatINR(booking.total_amount)}</span>
            </div>
            <p className="text-muted small mb-0">
              {booking.payment_id && <>{t('booking.paymentId')} {booking.payment_id} · </>}
              {booking.paid_at && <>{t('booking.ticket.paidAt', { when: formatDateTime(booking.paid_at) })}</>}
              {booking.checked_in_at && <> · {t('booking.ticket.checkedInAt', { when: formatDateTime(booking.checked_in_at) })}</>}
            </p>
            {booking.refund_status && (
              <div className={`alert ${booking.refund_status === 'failed' ? 'alert-danger' : 'alert-success'} small mt-3 mb-0`}>
                <i className="bi bi-arrow-counterclockwise me-1" aria-hidden="true" />
                <strong>{t(`booking.refund.${booking.refund_status}`)}:</strong> {t('booking.ticket.refundTo', { amount: formatINR(booking.refund_amount) })}
                {booking.refund_status === 'pending' && ` ${t('booking.ticket.refundDays')}`}
                {booking.refund_id && <span className="text-muted"> · {t('booking.ticket.refundRef')} {booking.refund_id}</span>}
              </div>
            )}
            {booking.status === 'cancelled' && !booking.refund_status && Number(booking.total_amount) > 0 && booking.paid_at && (
              <div className="alert alert-secondary small mt-3 mb-0">{t('booking.ticket.noRefundDue')}</div>
            )}
          </div>
          <div className="stub">
            {valid ? (
              <div className="qr">
                <QRCodeSVG value={booking.reference} size={150} />
              </div>
            ) : (
              <div className="text-muted">{t('booking.ticket.qrAfterPayment')}</div>
            )}
            <div className="ref">{booking.reference}</div>
            <div className="text-muted small">{t('booking.ticket.photoId')}</div>
          </div>
        </div>

        {emailNotice && (
          <div className={`alert ${emailNotice.ok ? 'alert-success' : 'alert-danger'} small mt-4 mb-0 no-print`} role="status">
            {emailNotice.text}
          </div>
        )}
        <div className="d-flex flex-wrap align-items-center gap-2 mt-4 no-print">
          {valid && (
            <button className="btn btn-accent" onClick={() => window.print()}>
              <i className="bi bi-printer me-2" aria-hidden="true" />
              {t('booking.ticket.print')}
            </button>
          )}
          {valid && (
            <button type="button" className="btn btn-outline-primary btn-sm" onClick={this.emailTicket} disabled={emailing}>
              <i className="bi bi-envelope me-2" aria-hidden="true" />
              {emailing ? t('booking.sending') : t('booking.ticket.emailMe')}
            </button>
          )}
          {valid && Number(booking.total_amount) > 0 && (
            <Link to={`/invoices/${booking.reference}`} className="btn btn-outline-primary btn-sm">
              <i className="bi bi-receipt me-2" aria-hidden="true" />
              {t('booking.ticket.taxInvoice')}
            </Link>
          )}
          {booking.status === 'pending' && <Link to={`/checkout/${booking.reference}`} className="btn btn-accent">{t('booking.checkout.title')}</Link>}
          <Link to="/my-bookings" className="btn btn-outline-primary">{t('booking.my.title')}</Link>
          {booking.can_cancel && <button className="btn btn-link text-danger" onClick={this.cancel}>{t('booking.cancelBooking')}</button>}
        </div>
        {booking.status === 'confirmed' && <ReminderSettings className="mt-3 no-print" />}
      </div>
    );
  }
}

export default withRouter(withI18n(Ticket));
