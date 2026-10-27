import * as React from 'react';
import { Link } from 'react-router-dom';
import type { MuseumSummary } from '../api/types';
import { withI18n, WithI18nProps } from '../i18n';
import FavouriteButton from './FavouriteButton';
import { formatPrice, museumGradient, sizedImage } from '../utils/format';
import PlaceCover from './PlaceCover';
import { placeLocation } from '../utils/format';

export function museumBackground(m: { image_url?: string; slug?: string; name: string }) {
  return m.image_url
    ? `linear-gradient(transparent 35%, rgba(4,14,34,.7)), url("${sizedImage(m.image_url, 1280)}") center/cover`
    : museumGradient(m.slug ?? m.name);
}

interface MuseumCardProps extends WithI18nProps {
  museum: MuseumSummary;
}

interface MuseumCardState {
  broken: boolean;
}

class MuseumCard extends React.Component<MuseumCardProps, MuseumCardState> {
  public state: MuseumCardState = { broken: false };

  private onImageError = (): void => {
    this.setState({ broken: true });
  };

  public render(): React.ReactNode {
    const { museum } = this.props;
    const { t } = this.props.i18n;
    const showPhoto = museum.image_url && !this.state.broken;

    return (
      <Link to={`/museums/${museum.slug}`} className="card border-0 shadow-sm h-100 place-card">
        <div className="place-thumb">
          {showPhoto ? (
            <>
              <img src={sizedImage(museum.image_url, 500)} alt="" loading="lazy" onError={this.onImageError} />
              {museum.photo_source === 'google' && <span className="photo-source-tag">Google Maps</span>}
            </>
          ) : (
            <PlaceCover seed={museum.slug} placeType={museum.place_type} category={museum.category_name} />
          )}
          <span className="position-absolute top-0 end-0 m-2" style={{ zIndex: 2 }}>
            <FavouriteButton slug={museum.slug} name={museum.name} />
          </span>
          <span className="place-badges">
            <span className={`badge ${museum.place_type === 'museum' ? 'bg-primary' : 'bg-accent'}`}>{t(`common.type.${museum.place_type}`)}</span>
            {museum.category_name && <span className="badge bg-light text-dark">{museum.category_name}</span>}
          </span>
        </div>
        <div className="card-body d-flex flex-column">
          <h3 className="card-title h5 mb-1">{museum.name}</h3>
          <div className="small text-muted mb-2">
            <i className="bi bi-geo-alt me-1" aria-hidden="true" />
            {placeLocation(museum.city_name, museum.state_name)}
          </div>
          {museum.tagline && <p className="small text-muted mb-3">{museum.tagline}</p>}
          <div className="mt-auto pt-2 border-top d-flex justify-content-between align-items-center">
            <span>
              {museum.starting_price === null ? (
                <span className="small text-muted">{t('common.card.ticketsSoon')}</span>
              ) : (
                <>
                  <span className="small text-muted">{t('common.card.from')}</span>
                  <span className="fw-bold text-accent">{Number(museum.starting_price) === 0 ? t('common.free') : formatPrice(museum.starting_price)}</span>
                </>
              )}
            </span>
            {museum.avg_rating ? (
              <span className="small fw-semibold">
                <i className="bi bi-star-fill text-warning me-1" aria-hidden="true" />
                {museum.avg_rating.toFixed(1)} <span className="text-muted fw-normal">({museum.review_count})</span>
              </span>
            ) : (
              <span className="badge bg-light text-dark">{t('common.new')}</span>
            )}
          </div>
        </div>
      </Link>
    );
  }
}

export default withI18n(MuseumCard);
