import * as React from 'react';
import type { Museum, MuseumImage } from '../api/types';
import { withI18n, WithI18nProps } from '../i18n';
import { sizedImage } from '../utils/format';
import PlaceCover from './PlaceCover';

const AUTOPLAY_MS = 5000;
const SWIPE_PX = 40;

/** Main photo first, then the gallery; every photo keeps its author/licence credit. */
export function placePhotos(museum: Museum): MuseumImage[] {
  return [
    ...(museum.image_url
      ? [{ id: 0, url: museum.image_url, caption: museum.name, credit: museum.image_credit, source_url: museum.image_source_url }]
      : []),
    ...museum.images.filter((p) => p.url !== museum.image_url),
  ];
}

interface PhotoCarouselProps extends WithI18nProps {
  museum: Museum;
  /** Badges, title and location drawn over the photos. */
  children?: React.ReactNode;
}

interface PhotoCarouselState {
  index: number;
  playing: boolean;
  hovering: boolean;
  fullscreen: boolean;
}

/**
 * Place-page hero carousel: cross-fading photos with arrows, dots, swipe, keyboard,
 * a thumbnail strip and a full-screen viewer. Autoplay pauses on hover/focus and when the
 * visitor prefers reduced motion.
 */
class PhotoCarouselBase extends React.Component<PhotoCarouselProps, PhotoCarouselState> {
  public state: PhotoCarouselState = { index: 0, playing: true, hovering: false, fullscreen: false };

  private timer: number | undefined;
  private touchX: number | null = null;
  private thumbs = React.createRef<HTMLDivElement>();
  private reducedMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  public componentDidMount(): void {
    if (this.reducedMotion) this.setState({ playing: false });
    this.schedule();
    document.addEventListener('visibilitychange', this.schedule);
  }

  public componentDidUpdate(prev: PhotoCarouselProps, prevState: PhotoCarouselState): void {
    if (prev.museum.slug !== this.props.museum.slug) {
      this.setState({ index: 0, fullscreen: false });
      return;
    }
    const s = this.state;
    if (s.index !== prevState.index || s.playing !== prevState.playing || s.hovering !== prevState.hovering || s.fullscreen !== prevState.fullscreen) {
      this.schedule();
    }
    if (s.index !== prevState.index) this.scrollThumbIntoView();
    if (s.fullscreen !== prevState.fullscreen) {
      if (s.fullscreen) window.addEventListener('keydown', this.onFullscreenKey);
      else window.removeEventListener('keydown', this.onFullscreenKey);
    }
  }

  public componentWillUnmount(): void {
    window.clearTimeout(this.timer);
    document.removeEventListener('visibilitychange', this.schedule);
    window.removeEventListener('keydown', this.onFullscreenKey);
  }

  private photos(): MuseumImage[] {
    return placePhotos(this.props.museum);
  }

  private schedule = (): void => {
    window.clearTimeout(this.timer);
    const { playing, hovering, fullscreen } = this.state;
    if (!playing || hovering || fullscreen || document.hidden || this.photos().length < 2) return;
    this.timer = window.setTimeout(() => this.step(1), AUTOPLAY_MS);
  };

  private go = (index: number): void => {
    const count = this.photos().length;
    if (count) this.setState({ index: (index + count) % count });
  };

  private step = (delta: number): void => {
    this.go(this.state.index + delta);
  };

  private scrollThumbIntoView(): void {
    const strip = this.thumbs.current;
    const el = strip?.children[this.state.index] as HTMLElement | undefined;
    if (!strip || !el) return;
    // Scroll only the strip, never the page.
    strip.scrollTo({ left: el.offsetLeft - strip.clientWidth / 2 + el.clientWidth / 2, behavior: this.reducedMotion ? 'auto' : 'smooth' });
  }

  private onKeyDown = (e: React.KeyboardEvent<HTMLElement>): void => {
    if (e.key === 'ArrowRight') { e.preventDefault(); this.step(1); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); this.step(-1); }
  };

  private onFullscreenKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') this.setState({ fullscreen: false });
    if (e.key === 'ArrowRight') this.step(1);
    if (e.key === 'ArrowLeft') this.step(-1);
  };

  private onTouchStart = (e: React.TouchEvent): void => {
    this.touchX = e.touches[0].clientX;
  };

  private onTouchEnd = (e: React.TouchEvent): void => {
    if (this.touchX === null) return;
    const dx = e.changedTouches[0].clientX - this.touchX;
    this.touchX = null;
    if (Math.abs(dx) > SWIPE_PX) this.step(dx < 0 ? 1 : -1);
  };

  private renderCredit(photo: MuseumImage, className: string): React.ReactNode {
    if (!photo.credit) return null;
    return photo.source_url ? (
      <a className={className} href={photo.source_url} target="_blank" rel="noreferrer" title={photo.credit}>{photo.credit}</a>
    ) : (
      <span className={className} title={photo.credit}>{photo.credit}</span>
    );
  }

  private renderFullscreen(photos: MuseumImage[]): React.ReactNode {
    const { museum } = this.props;
    const { t } = this.props.i18n;
    const { index } = this.state;
    const current = photos[index];
    return (
      <div className="lightbox" role="dialog" aria-modal="true" aria-label={t('common.carousel.label', { name: museum.name })} onClick={() => this.setState({ fullscreen: false })}>
        <figure className="m-0 text-center" onClick={(e) => e.stopPropagation()} onTouchStart={this.onTouchStart} onTouchEnd={this.onTouchEnd}>
          <img src={sizedImage(current.url, 1280)} alt={current.caption || museum.name} />
          <figcaption className="mt-2">
            {current.caption && current.caption !== museum.name && <div>{current.caption}</div>}
            <div className="small">{this.renderCredit(current, '')}</div>
          </figcaption>
          <div className="d-flex justify-content-between align-items-center mt-2">
            <button type="button" className="btn btn-light btn-sm" onClick={() => this.step(-1)}>
              <i className="bi bi-chevron-left me-1" aria-hidden="true" />
              {t('common.prev')}
            </button>
            <span className="small">{t('common.carousel.slide', { n: index + 1, total: photos.length })}</span>
            <button type="button" className="btn btn-light btn-sm" onClick={() => this.step(1)}>
              {t('common.next')}
              <i className="bi bi-chevron-right ms-1" aria-hidden="true" />
            </button>
          </div>
        </figure>
        <button
          type="button"
          className="btn-close btn-close-white position-absolute top-0 end-0 m-3"
          aria-label={t('common.close')}
          onClick={() => this.setState({ fullscreen: false })}
        />
      </div>
    );
  }

  public render(): React.ReactNode {
    const { museum, children } = this.props;
    const { t } = this.props.i18n;
    const { index, playing, fullscreen } = this.state;
    const photos = this.photos();
    const many = photos.length > 1;
    const current = photos[index];

    if (!photos.length) {
      // No photo yet: a designed cover (labelled as an illustration) behind the title.
      return (
        <div className="detail-hero mb-4">
          <PlaceCover seed={museum.slug ?? museum.name} placeType={museum.place_type} category={museum.category_name} size="hero" />
          <div className="hero-content">{children}</div>
        </div>
      );
    }

    return (
      <div className="mb-4">
        <section
          className="detail-hero photo-carousel"
          aria-roledescription="carousel"
          aria-label={t('common.carousel.label', { name: museum.name })}
          tabIndex={0}
          onKeyDown={this.onKeyDown}
          onMouseEnter={() => this.setState({ hovering: true })}
          onMouseLeave={() => this.setState({ hovering: false })}
          onFocus={() => this.setState({ hovering: true })}
          onBlur={() => this.setState({ hovering: false })}
          onTouchStart={this.onTouchStart}
          onTouchEnd={this.onTouchEnd}
        >
          <div className="slides" aria-live={playing ? 'off' : 'polite'}>
            {photos.map((p, i) => {
              // Load the current photo and its neighbours; the rest load when reached.
              const near = Math.abs(i - index) <= 1 || (index === 0 && i === photos.length - 1) || (index === photos.length - 1 && i === 0);
              return (
                <div
                  key={`${p.id}-${i}`}
                  className={`slide ${i === index ? 'active' : ''}`}
                  role="group"
                  aria-roledescription="slide"
                  aria-label={t('common.carousel.slide', { n: i + 1, total: photos.length })}
                  aria-hidden={i !== index}
                >
                  {near && <img src={sizedImage(p.url, 1280)} alt={i === index ? p.caption || museum.name : ''} loading={i === 0 ? 'eager' : 'lazy'} />}
                </div>
              );
            })}
          </div>

          <div className="hero-content">{children}</div>

          {many && (
            <>
              <button type="button" className="carousel-arrow prev" aria-label={t('common.prev')} onClick={() => this.step(-1)}>
                <i className="bi bi-chevron-left" aria-hidden="true" />
              </button>
              <button type="button" className="carousel-arrow next" aria-label={t('common.next')} onClick={() => this.step(1)}>
                <i className="bi bi-chevron-right" aria-hidden="true" />
              </button>
            </>
          )}

          <div className="carousel-tools">
            {many && (
              <button
                type="button"
                className="tool"
                aria-label={playing ? t('common.carousel.pause') : t('common.carousel.play')}
                title={playing ? t('common.carousel.pause') : t('common.carousel.play')}
                onClick={() => this.setState({ playing: !playing })}
              >
                <i className={`bi ${playing ? 'bi-pause-fill' : 'bi-play-fill'}`} aria-hidden="true" />
              </button>
            )}
            <button type="button" className="tool" onClick={() => this.setState({ fullscreen: true })} title={t('common.carousel.fullscreen')}>
              <i className="bi bi-arrows-fullscreen me-1" aria-hidden="true" />
              {many ? t('common.carousel.viewAll', { n: photos.length }) : t('common.carousel.fullscreen')}
            </button>
          </div>

          {many && (
            <div className="carousel-dots">
              {photos.map((p, i) => (
                <button
                  type="button"
                  key={`${p.id}-${i}`}
                  className={i === index ? 'active' : ''}
                  aria-label={t('common.carousel.go', { n: i + 1 })}
                  aria-current={i === index}
                  onClick={() => this.go(i)}
                />
              ))}
            </div>
          )}

          {this.renderCredit(current, 'hero-credit')}
        </section>

        {many && (
          <div className="carousel-thumbs" ref={this.thumbs}>
            {photos.map((p, i) => (
              <button
                type="button"
                key={`${p.id}-${i}`}
                className={i === index ? 'active' : ''}
                aria-label={t('common.carousel.go', { n: i + 1 })}
                aria-current={i === index}
                onClick={() => this.go(i)}
              >
                <img src={sizedImage(p.url, 330)} alt="" loading="lazy" />
              </button>
            ))}
          </div>
        )}

        {fullscreen && this.renderFullscreen(photos)}
      </div>
    );
  }
}

export default withI18n(PhotoCarouselBase);
