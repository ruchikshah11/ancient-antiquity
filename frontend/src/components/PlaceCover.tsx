import * as React from 'react';
import { museumGradient } from '../utils/format';

/** Motif per collection, then per place type: what the cover shows for a place without a photo. */
const CATEGORY_ICONS: Record<string, string> = {
  'Art & Sculpture': 'bi-palette',
  'Science & Technology': 'bi-gear-wide-connected',
  Military: 'bi-shield-shaded',
  'Natural History': 'bi-tree',
  Memorial: 'bi-flower1',
  'Tribal & Folk': 'bi-people',
  'Textiles & Crafts': 'bi-scissors',
  Archaeology: 'bi-columns-gap',
  'Palace Museum': 'bi-gem',
  Architecture: 'bi-bank',
  History: 'bi-hourglass-split',
};
const TYPE_ICONS: Record<string, string> = { fort: 'bi-shield-shaded', palace: 'bi-gem', monument: 'bi-bank', museum: 'bi-bank' };

interface PlaceCoverProps {
  seed: string;
  placeType?: string;
  category?: string | null;
  /** 'card' for Explore cards, 'hero' for the place-page banner. */
  size?: 'card' | 'hero';
}

/**
 * Designed cover for a place with no photo yet: the place's own colour, a jali (lattice) pattern and a motif for its
 * collection. An admin's uploaded photo (or a Google Maps photo) replaces it.
 */
export default class PlaceCover extends React.Component<PlaceCoverProps> {
  public render(): React.ReactNode {
    const { seed, placeType = 'museum', category, size = 'card' } = this.props;
    const icon = (category && CATEGORY_ICONS[category]) || TYPE_ICONS[placeType] || 'bi-bank';
    return (
      <span className={`place-cover place-cover-${size}`} style={{ background: museumGradient(seed) }} aria-hidden="true">
        <span className="place-cover-jali" />
        <i className={`bi ${icon} place-cover-motif`} />
      </span>
    );
  }
}
