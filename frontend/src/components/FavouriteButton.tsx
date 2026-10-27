import * as React from 'react';
import { errorMessage } from '../api/client';
import { FavouriteStore } from '../api/trips';
import { withAuth, WithAuthProps } from '../context/AuthContext';
import { withI18n, WithI18nProps } from '../i18n';
import { withRouter, WithRouterProps } from '../utils/withRouter';

interface OwnProps {
  slug: string;
  name: string;
  /** 'overlay': round white button for photo corners; 'button': outline button with a label. */
  variant?: 'overlay' | 'button';
  className?: string;
  onChange?: (favourite: boolean) => void;
}

type FavouriteButtonProps = OwnProps & WithAuthProps & WithI18nProps & WithRouterProps;

interface FavouriteButtonState {
  favourite: boolean;
  busy: boolean;
}

/** Heart toggle. Logged-out visitors are sent to /login and come back here afterwards. */
class FavouriteButton extends React.Component<FavouriteButtonProps, FavouriteButtonState> {
  public state: FavouriteButtonState = { favourite: FavouriteStore.has(this.props.slug), busy: false };

  private unsubscribe: (() => void) | null = null;

  public componentDidMount(): void {
    this.unsubscribe = FavouriteStore.subscribe(this.sync);
    this.load();
  }

  public componentDidUpdate(prev: FavouriteButtonProps): void {
    if (prev.auth.user?.id !== this.props.auth.user?.id || prev.slug !== this.props.slug) this.load();
  }

  public componentWillUnmount(): void {
    this.unsubscribe?.();
  }

  private load(): void {
    const { user, loading } = this.props.auth;
    if (loading) return;
    FavouriteStore.load(user ? String(user.id) : null).then(this.sync).catch(() => undefined);
  }

  private sync = (): void => {
    const favourite = FavouriteStore.has(this.props.slug);
    if (favourite !== this.state.favourite) this.setState({ favourite });
  };

  private onClick = (e: React.MouseEvent): void => {
    e.preventDefault();
    e.stopPropagation();
    const { auth, router, slug, onChange } = this.props;
    if (!auth.user) {
      router.navigate('/login', { state: { from: router.location.pathname + router.location.search } });
      return;
    }
    if (this.state.busy) return;
    const next = !this.state.favourite;
    this.setState({ busy: true, favourite: next });
    FavouriteStore.set(slug, next)
      .then(() => onChange?.(next))
      .catch((err) => window.alert(errorMessage(err, this.props.i18n.t('trips.fav.error'))))
      .finally(() => this.setState({ busy: false, favourite: FavouriteStore.has(slug) }));
  };

  public render(): React.ReactNode {
    const { name, variant = 'overlay', className = '' } = this.props;
    const { t } = this.props.i18n;
    const { favourite, busy } = this.state;
    const label = t(favourite ? 'trips.fav.remove' : 'trips.fav.add', { name });
    const icon = <i className={`bi ${favourite ? 'bi-heart-fill text-danger' : 'bi-heart'}`} aria-hidden="true" />;

    if (variant === 'button') {
      return (
        <button type="button" className={`btn btn-outline-danger ${className}`} aria-pressed={favourite} onClick={this.onClick} disabled={busy} title={label}>
          {icon}
          <span className="ms-2">{t(favourite ? 'trips.fav.saved' : 'trips.fav.save')}</span>
        </button>
      );
    }
    return (
      <button
        type="button"
        className={`btn btn-light btn-sm rounded-circle shadow-sm d-inline-flex align-items-center justify-content-center ${className}`}
        style={{ width: '2.25rem', height: '2.25rem', padding: 0 }}
        aria-pressed={favourite}
        aria-label={label}
        title={label}
        onClick={this.onClick}
        disabled={busy}
      >
        {icon}
      </button>
    );
  }
}

export default withRouter(withAuth(withI18n(FavouriteButton)));
