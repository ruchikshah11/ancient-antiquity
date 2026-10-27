import { api } from './client';
import type { PricingInsights, PricingRulePayload } from './types';

/** Weekday x slot fill rates and price suggestions for one place (panel users; staff: their places). */
export function getPricingSuggestions(museum: string, weeks: number, elasticity: number): Promise<PricingInsights> {
  return api
    .get<PricingInsights>('/admin/pricing-suggestions/', { params: { museum, weeks, elasticity } })
    .then((r) => r.data);
}

/** Create a price rule from a suggestion (existing price-rule admin API; administrators only). */
export function createPriceRule(rule: PricingRulePayload): Promise<{ id: number; name: string }> {
  return api.post<{ id: number; name: string }>('/admin/price-rules/', rule).then((r) => r.data);
}
