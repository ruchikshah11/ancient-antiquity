import * as React from 'react';
import type { Booking } from '../api/types';
import { withI18n, WithI18nProps } from '../i18n';
import type { I18nValue } from '../i18n';
import { formatINR } from '../utils/format';

/**
 * "40 visitors + 4 escorts" (total_visitors already includes the free escorts).
 * Pass the i18n `t` to get it in the current language; without it the text is English.
 */
export function groupHeadcount(b: Booking, t?: I18nValue['t']): string {
  const visitors = b.total_visitors - b.escort_count;
  const head = t
    ? t(visitors === 1 ? 'common.group.visitors.one' : 'common.group.visitors.other', { n: visitors })
    : `${visitors} visitor${visitors === 1 ? '' : 's'}`;
  if (b.escort_count === 0) return head;
  const escorts = t
    ? t(b.escort_count === 1 ? 'common.group.escorts.one' : 'common.group.escorts.other', { n: b.escort_count })
    : `${b.escort_count} escort${b.escort_count === 1 ? '' : 's'}`;
  return `${head} + ${escorts}`;
}

/** Discount as a whole percent of the subtotal, for display. */
export function discountPercent(b: Booking): number {
  const subtotal = Number(b.subtotal_amount);
  return subtotal > 0 ? Math.round((Number(b.discount_amount) / subtotal) * 100) : 0;
}

interface GroupPriceLinesProps extends WithI18nProps {
  booking: Booking;
}

/** Subtotal, group discount and free-escort lines shown above a group booking's total. */
class GroupPriceLinesBase extends React.Component<GroupPriceLinesProps> {
  public render(): React.ReactNode {
    const { booking } = this.props;
    const { t } = this.props.i18n;
    const discount = Number(booking.discount_amount);
    return (
      <div className="pt-2">
        <div className="d-flex justify-content-between py-1">
          <span>{t('common.group.subtotal')}</span>
          <span>{formatINR(booking.subtotal_amount)}</span>
        </div>
        {discount > 0 && (
          <div className="d-flex justify-content-between py-1 text-success">
            <span>{t('common.group.discount', { n: discountPercent(booking) })}</span>
            <span>−{formatINR(discount)}</span>
          </div>
        )}
        {booking.escort_count > 0 && (
          <div className="d-flex justify-content-between py-1">
            <span>{t(booking.escort_count === 1 ? 'common.group.escorts.one' : 'common.group.escorts.other', { n: booking.escort_count })}</span>
            <span className="text-success">{t('common.free')}</span>
          </div>
        )}
      </div>
    );
  }
}

export const GroupPriceLines = withI18n(GroupPriceLinesBase);
