/** Pure text for a headline's sentiment score (N panel, detail line). Only Marketaux scores its articles; every other source gives null. */

/** "SENTIMENT +0.50 POSITIVE (SOURCE'S SCORE, -1 TO +1)" or "" when the source gave no score. The number is the source's, never ours. */
export function sentimentText(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "";
  const word = score > 0.05 ? "POSITIVE" : score < -0.05 ? "NEGATIVE" : "NEUTRAL";
  return `SENTIMENT ${score > 0 ? "+" : ""}${score.toFixed(2)} ${word} (MARKETAUX SCORE, -1 TO +1)`;
}

/** Color class for the score: green / red only when it is clearly positive / negative (color carries meaning only). */
export function sentimentClass(score: number | null | undefined): "up" | "down" | "dim" {
  if (score == null || !Number.isFinite(score)) return "dim";
  return score > 0.05 ? "up" : score < -0.05 ? "down" : "dim";
}
