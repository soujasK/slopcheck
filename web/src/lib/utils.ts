import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Assessment, EngineKey } from "./api";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const PICTO = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{200D}]/gu;
export const clean = (s?: string | null) => String(s ?? "").replace(PICTO, "").replace(/\s+/g, " ").trim();

export function host(u: string) {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; }
}

export const pct = (x?: number | null) =>
  x == null ? "–" : `${x > 0 && x < 0.1 ? (x * 100).toFixed(1) : Math.round(x * 100)}%`;

export const ENGINES: { key: EngineKey; name: string; short: string }[] = [
  { key: "google-in", name: "Google India", short: "Google IN" },
  { key: "duckduckgo-in", name: "DuckDuckGo India", short: "DuckDuckGo IN" },
  { key: "yahoo-in", name: "Yahoo India", short: "Yahoo IN" },
  { key: "google-us", name: "Google US", short: "Google US" },
];
/** "3 Oct 2026" for a cached snapshot; null when the search ran just now. */
export function snapshotLabel(iso: string | null, cached: boolean) {
  if (!iso || !cached) return null;
  const d = new Date(iso);
  return isNaN(+d) ? null : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export const engineName = (k: EngineKey) => ENGINES.find((e) => e.key === k)?.name ?? k;

export type Verdict = "slop" | "clear" | "borderline" | "platform" | "unreadable" | "pending";

export function verdict(s: Assessment | undefined, threshold: number): Verdict {
  if (!s) return "pending";
  if (s.slop_risk != null && s.slop_risk >= threshold) return "slop";
  if (s.band) return s.band === "mixed" ? "borderline" : "clear";
  if (s.not_scored?.startsWith("platform:")) return "platform";
  return "unreadable";
}

export function verdictLabel(s: Assessment | undefined, threshold: number) {
  const v = verdict(s, threshold);
  if (v === "pending") return "reading";
  if (v === "platform") return s!.not_scored!.slice(9).replace("_", " ");
  if (v === "unreadable") return s?.not_scored === "too_little_text" ? "too little text" : "not readable";
  if (v === "borderline") return "clear · borderline";
  return v;
}

/** A reason is protective when it comes from a negative-weight rule (templates from /api/rubric). */
export function protectiveMatchers(rules: { weight: number; reason: string }[]) {
  return rules
    .filter((r) => r.weight < 0)
    .map((r) => new RegExp("^" + r.reason.split(/\{[^}]+\}/).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$"));
}

export function store<T>(key: string, value?: T): T | null {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key) ?? "null") as T | null;
    localStorage.setItem(key, JSON.stringify(value));
  } catch { /* private window or blocked storage: the app works without it */ }
  return null;
}
