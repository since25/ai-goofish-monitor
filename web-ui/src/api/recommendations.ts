import { http } from '@/lib/http'
import type { RecommendationSummary } from '@/types/recommendation.d.ts'

export interface GetRecommendationParams {
  task?: string;
  top?: number;
}

export async function getRecommendationSummary(
  params: GetRecommendationParams = {},
): Promise<RecommendationSummary> {
  return await http('/api/recommendations/summary', {
    params: params as Record<string, string | number | undefined>,
  })
}
