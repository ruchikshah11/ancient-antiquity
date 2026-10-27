import * as React from 'react';
import { api } from '../api/client';
import type { MuseumSummary, Paginated } from '../api/types';

interface MuseumPickerProps {
  value: string;
  onChange: (slug: string, name: string) => void;
  /** Label above the input (defaults to the desk wording). */
  label?: string;
  /** Show a "Clear" link that resets the choice to '' (e.g. "all places" in reports). */
  clearable?: boolean;
  /**
   * Filter-bar mode: same height as the selects/inputs beside it. The label is kept for screen readers
   * only, the chosen place shows inside the box and a × button clears it.
   */
  filter?: boolean;
  /** Like filter mode (choice inside the box, × to clear, no margin) but with the label shown above. */
  compact?: boolean;
}

let pickerIds = 0;

interface MuseumPickerState {
  search: string;
  options: MuseumSummary[];
  current: MuseumSummary | null;
  /** How many places this user may work at (staff: assigned ones; admins: all). null until loaded. */
  assignedCount: number | null;
}

/** Desk museum chooser. Searches only the places assigned to the signed-in staff member (admins: all). */
export default class MuseumPicker extends React.Component<MuseumPickerProps, MuseumPickerState> {
  public state: MuseumPickerState = { search: '', options: [], current: null, assignedCount: null };

  private readonly inputId = `museum-pick-${++pickerIds}`;
  private mounted = false;
  private searchTimer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
    this.loadCurrent();
    this.loadAssigned();
  }

  public componentDidUpdate(prevProps: MuseumPickerProps, prevState: MuseumPickerState): void {
    if (prevProps.value !== this.props.value || prevState.current !== this.state.current) this.loadCurrent();
    if (prevState.search !== this.state.search) this.scheduleSearch();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.searchTimer);
  }

  private loadCurrent(): void {
    const { value } = this.props;
    if (value && this.state.current?.slug !== value) {
      api
        .get<MuseumSummary>(`/museums/${value}/`)
        .then((r) => this.mounted && this.setState({ current: r.data }))
        .catch(() => this.mounted && this.setState({ current: null }));
    }
  }

  /** A staff member with exactly one place gets it preselected. */
  private loadAssigned(): void {
    api
      .get<Paginated<MuseumSummary>>('/museums/', { params: { assigned: 1 } })
      .then((r) => {
        if (!this.mounted) return;
        this.setState({ assignedCount: r.data.count });
        const only = r.data.count === 1 ? r.data.results[0] : null;
        if (only && this.props.value !== only.slug) this.choose(only);
      })
      .catch(() => undefined);
  }

  private scheduleSearch(): void {
    clearTimeout(this.searchTimer);
    const { search } = this.state;
    if (!search.trim()) {
      this.setState({ options: [] });
      return;
    }
    this.searchTimer = setTimeout(() => {
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search, assigned: 1 } })
        .then((r) => this.mounted && this.setState({ options: r.data.results }));
    }, 250);
  }

  private clear = (): void => {
    this.setState({ current: null, search: '', options: [] });
    this.props.onChange('', '');
  };

  private choose = (m: MuseumSummary): void => {
    this.setState({ current: m, search: '', options: [] });
    this.props.onChange(m.slug, m.name);
  };

  private renderOptions(): React.ReactNode {
    const { options } = this.state;
    if (!options.length) return null;
    return (
      <div className="list-group shadow position-absolute w-100" style={{ top: '100%', left: 0, zIndex: 10, maxHeight: 280, overflowY: 'auto' }}>
        {options.map((m) => (
          <button type="button" key={m.id} className="list-group-item list-group-item-action" onClick={() => this.choose(m)}>
            {m.name} <span className="small text-muted">· {m.city_name}</span>
          </button>
        ))}
      </div>
    );
  }

  private renderFilter(): React.ReactNode {
    const { search, current } = this.state;
    const label = this.props.label ?? 'Place';
    return (
      <div className="position-relative museum-filter">
        <label htmlFor={this.inputId} className={this.props.filter ? 'visually-hidden' : 'form-label'}>{label}</label>
        <div className="input-group">
          <span className="input-group-text bg-white"><i className="bi bi-building text-muted" aria-hidden="true" /></span>
          <input
            id={this.inputId}
            className={`form-control border-start-0 ps-0 ${current && !search ? 'has-value' : ''}`}
            placeholder={current ? `${current.name} · ${current.city_name}` : this.props.clearable ? 'All places' : 'Type to search museum…'}
            title={current ? `${current.name}, ${current.city_name}` : label}
            value={search}
            onChange={(e) => this.setState({ search: e.target.value })}
            autoComplete="off"
          />
          {current && this.props.clearable && (
            <button type="button" className="btn btn-outline-secondary border-start-0 bg-white" onClick={this.clear} aria-label={`Clear ${label.toLowerCase()}`} title="Clear">
              <i className="bi bi-x-lg" aria-hidden="true" />
            </button>
          )}
        </div>
        {this.renderOptions()}
      </div>
    );
  }

  public render(): React.ReactNode {
    const { search, current, assignedCount } = this.state;
    const single = assignedCount === 1 && current !== null;
    if ((this.props.filter || this.props.compact) && assignedCount !== 0 && !single) return this.renderFilter();
    return (
      <div className="mb-3 position-relative">
        <label htmlFor={this.inputId} className="form-label">{this.props.label ?? 'Museum at this desk'}</label>
        {assignedCount === 0 ? (
          <div className="alert alert-warning mb-0">
            <i className="bi bi-exclamation-triangle me-2" />
            You are not assigned to any museum yet. Ask an administrator to assign you to your place.
          </div>
        ) : single ? (
          <div className="form-control bg-light">
            <i className="bi bi-building me-2 text-muted" />
            <strong>{current.name}</strong> <span className="text-muted">· {current.city_name}</span>
          </div>
        ) : (
          <>
            <input
              id={this.inputId}
              className="form-control"
              placeholder={current ? current.name : 'Type to search museum…'}
              value={search}
              onChange={(e) => this.setState({ search: e.target.value })}
              autoComplete="off"
            />
            {current && !search && (
              <div className="form-text">
                Selected: <strong className="text-body">{current.name}</strong>, {current.city_name}
                {this.props.clearable && (
                  <button type="button" className="btn btn-link btn-sm p-0 ms-2 align-baseline" onClick={this.clear}>Clear</button>
                )}
              </div>
            )}
          </>
        )}
        {this.renderOptions()}
      </div>
    );
  }
}
