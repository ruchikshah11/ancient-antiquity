import * as React from 'react';

/** Label every day up to a month; on longer ranges label every Nth day so the axis stays readable. */
export function tickEvery(days: number): number {
  return days <= 31 ? 1 : Math.ceil(days / 16);
}

interface DayTickProps {
  /** ISO dates (YYYY-MM-DD) of the whole axis. */
  dates: string[];
  index: number;
  every: number;
}

/**
 * Compact x-axis label under one chart column: the day number, plus the month on the first column
 * and wherever the month changes ("11 Oct", 12, 13 … "1 Nov").
 */
export class DayTick extends React.Component<DayTickProps> {
  public render(): React.ReactNode {
    const { dates, index, every } = this.props;
    const last = dates.length - 1;
    const shown = index % every === 0 || index === last;
    const [, month, day] = dates[index].split('-');
    const newMonth = index === 0 || dates[index - 1]?.slice(5, 7) !== month;
    const monthName = new Date(`${dates[index]}T00:00:00`).toLocaleDateString('en-IN', { month: 'short' });
    return (
      <span className="tick" style={{ visibility: shown ? 'visible' : 'hidden' }}>
        {Number(day)}
        {newMonth && <span className="tick-month">{monthName}</span>}
      </span>
    );
  }
}
