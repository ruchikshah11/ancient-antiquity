import * as React from 'react';
import { FxRates, getCurrency, loadFxRates, onCurrencyChange } from '../api/donations';
import { withI18n, WithI18nProps } from '../i18n';
import { formatForeign } from '../utils/format';

/*
 * <FxHint amount={inr} />: "≈ $6.00" in small muted text, only when the visitor picked a foreign currency in the
 * the currency part of the Navbar language menu. Rates are fetched once per page load (shared by every hint). Prices are always paid in rupees.
 */

interface FxHintProps extends WithI18nProps {
  amount: number | string | null | undefined;
  className?: string;
}

interface FxHintState {
  currency: string;
  rates: FxRates | null;
}

class FxHintBase extends React.Component<FxHintProps, FxHintState> {
  public state: FxHintState = { currency: getCurrency(), rates: null };

  private mounted = false;
  private unsubscribe: (() => void) | null = null;

  public componentDidMount(): void {
    this.mounted = true;
    this.unsubscribe = onCurrencyChange(this.refresh);
    this.refresh();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    this.unsubscribe?.();
  }

  private refresh = (): void => {
    const currency = getCurrency();
    this.setState({ currency });
    if (currency !== 'INR' && !this.state.rates) {
      loadFxRates().then((rates) => this.mounted && rates && this.setState({ rates }));
    }
  };

  public render(): React.ReactNode {
    const { amount, className } = this.props;
    const { currency, rates } = this.state;
    const value = Number(amount ?? 0);
    const rate = rates?.rates[currency];
    if (currency === 'INR' || !rate || !value) return null;
    const tip = this.props.i18n.t('giving.fx.tooltip');
    return (
      <small className={`fx-hint text-muted text-nowrap ${className ?? ''}`} title={tip}>
        ≈ {formatForeign(value * rate, currency)}
        <span className="visually-hidden"> ({tip})</span>
      </small>
    );
  }
}

const FxHint = withI18n(FxHintBase);
export default FxHint;
