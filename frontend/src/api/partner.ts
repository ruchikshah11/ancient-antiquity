import { api } from './client';
import type { PartnerMe, PartnerOverview, PartnerReviews, PartnerSettlement, PartnerTrend } from './types';

/** Read-only partner portal (role partner). `museum` narrows to one of the partner's places. */
const params = (museum?: string, extra: Record<string, unknown> = {}) => ({ params: { museum: museum || undefined, ...extra } });

export const getPartnerMe = (): Promise<PartnerMe> => api.get<PartnerMe>('/partner/me/').then((r) => r.data);

export const getPartnerOverview = (museum?: string): Promise<PartnerOverview> =>
  api.get<PartnerOverview>('/partner/overview/', params(museum)).then((r) => r.data);

export const getPartnerTrend = (days: 30 | 90, museum?: string): Promise<PartnerTrend> =>
  api.get<PartnerTrend>('/partner/trend/', params(museum, { days })).then((r) => r.data);

export const getPartnerReviews = (museum?: string, offset = 0, limit = 10): Promise<PartnerReviews> =>
  api.get<PartnerReviews>('/partner/reviews/', params(museum, { offset, limit })).then((r) => r.data);

export const getPartnerSettlements = (museum?: string): Promise<PartnerSettlement[]> =>
  api.get<{ results: PartnerSettlement[] }>('/partner/settlements/', params(museum)).then((r) => r.data.results);
