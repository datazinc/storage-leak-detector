/**
 * Format timestamp for chart axes. Uses date+time when data spans multiple days,
 * otherwise time only to avoid redundancy.
 */
export function formatChartTime(
  timestamp: string,
  allTimestamps?: string[]
): string {
  const d = new Date(timestamp);
  const needsDate =
    allTimestamps &&
    allTimestamps.length > 1 &&
    new Set(allTimestamps.map((t) => new Date(t).toDateString())).size > 1;
  if (needsDate) {
    return d.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
