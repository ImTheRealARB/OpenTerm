/** Which indicators to drop and which to compute when the wanted list changes (order of `want` kept for additions). */
export function diffIndicators<T extends string>(applied: Iterable<T>, want: readonly T[]): { add: T[]; remove: T[] } {
  const have = new Set(applied);
  const wanted = new Set(want);
  const add: T[] = [];
  for (const w of want) if (!have.has(w) && !add.includes(w)) add.push(w);
  const remove = [...have].filter((h) => !wanted.has(h));
  return { add, remove };
}
