import * as React from 'react';
import type { Museum, MuseumImage } from '../api/types';
import { withI18n, WithI18nProps } from '../i18n';
import { sizedImage } from '../utils/format';

interface DescriptionProps extends WithI18nProps {
  museum: Museum;
}

interface DescriptionState {
  expanded: boolean;
}

/** Renders the stored description: "## Heading" / "### Sub" lines become headings, the rest paragraphs. */
class DescriptionBase extends React.Component<DescriptionProps, DescriptionState> {
  public state: DescriptionState = { expanded: false };

  private toggle = (): void => {
    this.setState({ expanded: !this.state.expanded });
  };

  public render(): React.ReactNode {
    const { museum } = this.props;
    const { t } = this.props.i18n;
    const { expanded } = this.state;
    const blocks = museum.description.split('\n').filter((l) => l.trim());
    const long = museum.description.length > 1400;
    // Collapsed view: everything up to the first section heading, at most 3 paragraphs.
    const firstHeading = blocks.findIndex((b) => b.startsWith('#'));
    const intro = blocks.slice(0, Math.min(firstHeading === -1 ? blocks.length : firstHeading, 3));
    const shown = !long || expanded ? blocks : intro;

    return (
      <div className="story">
        {shown.map((b, i) =>
          b.startsWith('### ') ? (
            <h4 key={i}>{b.slice(4)}</h4>
          ) : b.startsWith('## ') ? (
            <h3 key={i}>{b.slice(3)}</h3>
          ) : (
            <p key={i}>{b}</p>
          ),
        )}
        {long && (
          <button type="button" className="btn btn-outline-primary btn-sm mt-2" onClick={this.toggle}>
            <i className={`bi ${expanded ? 'bi-chevron-up' : 'bi-book'} me-1`} aria-hidden="true" />
            {expanded ? t('common.story.showLess') : t('common.story.readMore')}
          </button>
        )}
        {museum.source_url && (
          <p className="small text-muted mt-3 mb-0">
            {t('common.story.credit')
              .split(/(\{wiki\}|\{license\})/)
              .map((part, i) =>
                part === '{wiki}' ? (
                  <a key={i} href={museum.source_url} target="_blank" rel="noreferrer">Wikipedia</a>
                ) : part === '{license}' ? (
                  <a key={i} href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">CC BY-SA 4.0</a>
                ) : (
                  <React.Fragment key={i}>{part}</React.Fragment>
                ),
              )}
          </p>
        )}
      </div>
    );
  }
}

export const Description = withI18n(DescriptionBase);

interface GalleryProps extends WithI18nProps {
  museum: Museum;
}

interface GalleryState {
  open: number | null;
}

/** Photo strip with a full-size viewer; every photo keeps its author/licence credit. */
class GalleryBase extends React.Component<GalleryProps, GalleryState> {
  public state: GalleryState = { open: null };

  private listening = false;

  public componentDidUpdate(): void {
    // Listen for keys only while the viewer is open.
    if (this.state.open !== null) this.attach();
    else this.detach();
  }

  public componentWillUnmount(): void {
    this.detach();
  }

  private getPhotos(): MuseumImage[] {
    const { museum } = this.props;
    return [
      ...(museum.image_url
        ? [{ id: 0, url: museum.image_url, caption: museum.name, credit: museum.image_credit, source_url: museum.image_source_url }]
        : []),
      ...museum.images,
    ];
  }

  private setOpen = (open: number | null): void => {
    this.setState({ open });
  };

  private step = (delta: number): void => {
    const count = this.getPhotos().length;
    this.setState(({ open }) => ({ open: open === null ? open : (open + delta + count) % count }));
  };

  private onKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') this.setOpen(null);
    if (e.key === 'ArrowRight') this.step(1);
    if (e.key === 'ArrowLeft') this.step(-1);
  };

  private attach(): void {
    if (this.listening) return;
    window.addEventListener('keydown', this.onKey);
    this.listening = true;
  }

  private detach(): void {
    if (!this.listening) return;
    window.removeEventListener('keydown', this.onKey);
    this.listening = false;
  }

  public render(): React.ReactNode {
    const { museum } = this.props;
    const { t } = this.props.i18n;
    const { open } = this.state;
    const photos = this.getPhotos();

    if (photos.length < 2) return null;
    const current = open === null ? null : photos[open];

    return (
      <>
        <h3 className="mt-4 mb-3">{t('common.story.photos')}</h3>
        <div className="gallery-grid">
          {photos.map((p, i) => (
            <button type="button" key={`${p.id}-${i}`} onClick={() => this.setOpen(i)} aria-label={t('common.story.openPhoto', { n: i + 1 })}>
              <img src={sizedImage(p.url, 330)} alt={p.caption || museum.name} loading="lazy" />
            </button>
          ))}
        </div>
        {current && (
          <div className="lightbox" role="dialog" aria-modal="true" onClick={() => this.setOpen(null)}>
            <figure className="m-0 text-center" onClick={(e) => e.stopPropagation()}>
              <img src={sizedImage(current.url, 1280)} alt={current.caption || museum.name} />
              <figcaption className="mt-2">
                {current.caption && <div>{current.caption}</div>}
                <div className="small">
                  {current.source_url ? (
                    <a href={current.source_url} target="_blank" rel="noreferrer">{current.credit || t('common.source')}</a>
                  ) : (
                    current.credit
                  )}
                </div>
              </figcaption>
              <div className="d-flex justify-content-between align-items-center mt-2">
                <button type="button" className="btn btn-light btn-sm" onClick={() => this.setOpen((open! - 1 + photos.length) % photos.length)}>
                  <i className="bi bi-chevron-left me-1" aria-hidden="true" />
                  {t('common.prev')}
                </button>
                <span className="small">{open! + 1} / {photos.length}</span>
                <button type="button" className="btn btn-light btn-sm" onClick={() => this.setOpen((open! + 1) % photos.length)}>
                  {t('common.next')}
                  <i className="bi bi-chevron-right ms-1" aria-hidden="true" />
                </button>
              </div>
            </figure>
            <button
              type="button"
              className="btn-close btn-close-white position-absolute top-0 end-0 m-3"
              aria-label={t('common.close')}
              onClick={() => this.setOpen(null)}
            />
          </div>
        )}
      </>
    );
  }
}

export const Gallery = withI18n(GalleryBase);
