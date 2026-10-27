import * as React from 'react';
import { Location, NavigateFunction, Params, SetURLSearchParams, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';

/*
 * React Router v6 exposes routing only through hooks, which class components cannot call.
 * This wrapper is the single place that uses hooks: it reads the router state and passes it to the
 * wrapped class component as the `router` prop.
 */

export interface RouterInfo {
  navigate: NavigateFunction;
  location: Location;
  params: Readonly<Params<string>>;
  searchParams: URLSearchParams;
  setSearchParams: SetURLSearchParams;
}

export interface WithRouterProps {
  router: RouterInfo;
}

export function withRouter<P extends WithRouterProps>(Component: React.ComponentType<P>) {
  function WithRouter(props: Omit<P, keyof WithRouterProps>) {
    const navigate = useNavigate();
    const location = useLocation();
    const params = useParams();
    const [searchParams, setSearchParams] = useSearchParams();
    return <Component {...(props as P)} router={{ navigate, location, params, searchParams, setSearchParams }} />;
  }
  WithRouter.displayName = `withRouter(${Component.displayName ?? Component.name})`;
  return WithRouter;
}
