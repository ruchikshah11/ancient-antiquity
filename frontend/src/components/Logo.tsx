import * as React from 'react';
import { Link } from 'react-router-dom';

interface PillarIconProps {
  size?: number;
}

export class PillarIcon extends React.Component<PillarIconProps> {
  public render(): React.ReactNode {
    const { size = 20 } = this.props;
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M2 9 12 3l10 6H2Zm2 2h3v8H4zm6.5 0h3v8h-3zM17 11h3v8h-3zM2 20h20v2H2z" />
      </svg>
    );
  }
}

interface LogoProps {
  to?: string;
}

export default class Logo extends React.Component<LogoProps> {
  public render(): React.ReactNode {
    const { to = '/' } = this.props;
    return (
      <Link to={to} className="navbar-brand d-flex align-items-center gap-2">
        <span className="brand-mark">
          <PillarIcon />
        </span>
        Ancient Antiquity
      </Link>
    );
  }
}
