// Word-level diff (longest common subsequence) between the two agent answers.

export interface Tok { text: string; changed: boolean }

// citation groups such as "[1, 3]" stay one token, so chips survive the diff
const split = (s: string) => s.match(/\S*\[\d+(?:\s*,\s*\d+)*\]\S*|\S+|\s+/g) ?? [];
const norm = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

/** Marks, in each answer, the words the other answer does not share. Whitespace never counts. */
export function wordDiff(a: string, b: string): { a: Tok[]; b: Tok[]; changed: number } {
  const A = split(a), B = split(b);
  const wa = A.map((t, i) => [norm(t), i] as const).filter(([w]) => w);
  const wb = B.map((t, i) => [norm(t), i] as const).filter(([w]) => w);
  const n = wa.length, m = wb.length;
  if (n * m > 250_000) return { a: A.map((t) => ({ text: t, changed: false })), b: B.map((t) => ({ text: t, changed: false })), changed: 0 };
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = wa[i][0] === wb[j][0] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const keepA = new Set<number>(), keepB = new Set<number>();
  for (let i = 0, j = 0; i < n && j < m; ) {
    if (wa[i][0] === wb[j][0]) { keepA.add(wa[i][1]); keepB.add(wb[j][1]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
    else j++;
  }
  const mark = (T: string[], keep: Set<number>) => T.map((t, i) => ({ text: t, changed: !!norm(t) && !keep.has(i) }));
  const ta = mark(A, keepA), tb = mark(B, keepB);
  return { a: ta, b: tb, changed: ta.filter((t) => t.changed).length + tb.filter((t) => t.changed).length };
}
