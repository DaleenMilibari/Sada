import type { AudienceSummary } from '../types';

// Classified comments, the share aimed at SBA itself (not reactions to the news), and a count per intent.
export function audienceShares(summary: AudienceSummary) {
  const count = (k: string) => summary.intents.find((i) => i.intent === k)?.count ?? 0;
  const classified = summary.totals.classified;
  const directed = classified - count('reaction') - count('other');
  return { classified, directed, count };
}
