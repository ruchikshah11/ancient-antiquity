import type { AxiosError } from 'axios';
import * as React from 'react';
import { AuthResult, isChallenge, TokenResult, TwoFactorRequiredError } from '../api/auth2';
import { api, tokens } from '../api/client';
import type { User } from '../api/types';

const USER_KEY = 'aa_user';

export interface RegisterInput {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  phone: string;
}

export interface AuthValue {
  user: User | null;
  loading: boolean;
  /** Throws TwoFactorRequiredError (with a ticket) when the account uses two-step verification. */
  login: (email: string, password: string) => Promise<User>;
  /** Store tokens from any sign-in endpoint (Google, one-time code, two-step verification). */
  loginWithTokens: (data: TokenResult) => User;
  register: (input: RegisterInput) => Promise<User>;
  logout: () => void;
  setUser: (u: User | null) => void;
}

/** Class components read this with `static contextType = AuthContext` or the `withAuth` wrapper. */
export const AuthContext = React.createContext<AuthValue | null>(null);

interface AuthProviderProps {
  children: React.ReactNode;
}

interface AuthProviderState {
  user: User | null;
  loading: boolean;
}

export class AuthProvider extends React.Component<AuthProviderProps, AuthProviderState> {
  public state: AuthProviderState = { user: null, loading: true };

  public componentDidMount(): void {
    if (!tokens.access) {
      this.setState({ loading: false });
      return;
    }
    api
      .get<User>('/auth/me/')
      .then((r) => this.setUser(r.data))
      .catch((err: AxiosError) => {
        if (err.response) {
          tokens.clear();
          this.setUser(null);
          return;
        }
        // No connection (e.g. gate device offline): keep the session with the last known user.
        try {
          const cached = localStorage.getItem(USER_KEY);
          if (cached) this.setState({ user: JSON.parse(cached) });
        } catch {
          /* ignore */
        }
      })
      .finally(() => this.setState({ loading: false }));
  }

  private setUser = (u: User | null): void => {
    this.setState({ user: u });
    try {
      if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
      else localStorage.removeItem(USER_KEY);
    } catch {
      /* storage unavailable */
    }
  };

  private login = async (email: string, password: string): Promise<User> => {
    const { data } = await api.post<AuthResult>('/auth/login/', { email, password });
    if (isChallenge(data)) throw new TwoFactorRequiredError(data.ticket);
    return this.loginWithTokens(data);
  };

  private loginWithTokens = (data: TokenResult): User => {
    tokens.set(data.access, data.refresh);
    this.setUser(data.user);
    return data.user;
  };

  private register = async (input: RegisterInput): Promise<User> => {
    const { data } = await api.post('/auth/register/', input);
    tokens.set(data.access, data.refresh);
    this.setUser(data.user);
    return data.user as User;
  };

  private logout = (): void => {
    tokens.clear();
    this.setUser(null);
  };

  // Stable functions + a new object only when user/loading change, so consumers don't re-render needlessly.
  private value: AuthValue | null = null;

  private getValue(): AuthValue {
    const { user, loading } = this.state;
    if (!this.value || this.value.user !== user || this.value.loading !== loading) {
      this.value = { user, loading, login: this.login, loginWithTokens: this.loginWithTokens, register: this.register, logout: this.logout, setUser: this.setUser };
    }
    return this.value;
  }

  public render(): React.ReactNode {
    return <AuthContext.Provider value={this.getValue()}>{this.props.children}</AuthContext.Provider>;
  }
}

export interface WithAuthProps {
  auth: AuthValue;
}

/** Injects `auth` into a class component. */
export function withAuth<P extends WithAuthProps>(Component: React.ComponentType<P>) {
  class WithAuth extends React.Component<Omit<P, keyof WithAuthProps>> {
    public static displayName = `withAuth(${Component.displayName ?? Component.name})`;

    public render(): React.ReactNode {
      return (
        <AuthContext.Consumer>
          {(auth) => {
            if (!auth) throw new Error('withAuth must be used inside AuthProvider');
            return <Component {...(this.props as P)} auth={auth} />;
          }}
        </AuthContext.Consumer>
      );
    }
  }
  return WithAuth;
}
