// Typed client for the `slopwatch serve` API (slopwatch/serve.py). Same three-step
// workflow as before: start (SerpApi search) -> step (read + score one page) -> answer.

export type EngineKey = "google-in" | "duckduckgo-in" | "yahoo-in" | "google-us";

export interface Credits {
  session_spent: number;
  session_cap: number;
  project_spent: number;
  project_cap: number;
}

export interface Result {
  position: number;
  title: string;
  link: string;
  snippet?: string | null;
}

export interface Assessment {
  slop_risk: number | null;
  band: "ok" | "mixed" | "low" | null;
  reasons: string[];
  not_scored: string | null;
}

export interface StartResponse extends Credits {
  job: string;
  query: string;
  engine: EngineKey;
  threshold: number;
  results: Result[];
  cached: boolean;
  credit_spent: number;
  agent: boolean;
}

export interface StepResponse {
  index?: number;
  link?: string;
  slopwatch?: Assessment;
  done: boolean;
  progress: [number, number];
}

export interface AnswerSource { n: number; link: string; band: Assessment["band"]; not_scored: string | null }
export interface AgentAnswer { answer: string; sources: AnswerSource[]; cited: AnswerSource[] }
export interface AnswerResponse { dropped: string[]; same_sources: boolean; before: AgentAnswer; after: AgentAnswer }

export interface Rule { id: string; weight: number; reason: string }
export interface Rubric { version: number; low: number; mixed: number; rules: Rule[] }

export interface Share {
  value: number;
  ci: [number, number];
  n_scored: number;
  n_rows: number;
  coverage: number;
  bounds: [number, number];
  corrected: number | null;
}
export interface EvalSummary { n: number; precision: number; precision_ci: [number, number]; recall: number; f1: number; specificity: number | null }
export interface Overview {
  rubric_version: number;
  n_searches: number;
  n_rows: number;
  collected: string;
  overall_india: Share;
  rogan_gladen_overall: number | null;
  by_engine: Record<string, Share>;
  by_category: Record<string, Share>;
  india_vs_us?: Record<"IN" | "US", Share>;
  comparisons?: Record<string, { diff: number; ci: [number, number]; p: number; n_pairs: number }>;
  ai_overview: Record<string, string>;
  platform_share: Record<string, { share: number }>;
  validation: Partial<Record<"round2_test" | "round3_test" | "round4_test", EvalSummary>>;
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public body?: unknown) { super(message); }
}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError("The local server stopped. Restart it with: slopwatch serve", 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError((body as { error?: string }).error || `HTTP ${res.status}`, res.status, body);
  return body as T;
}

export const api = {
  start: (q: string, engine: EngineKey) =>
    get<StartResponse>(`/api/start?q=${encodeURIComponent(q)}&engine=${encodeURIComponent(engine)}`),
  step: (job: string) => get<StepResponse>(`/api/step?job=${encodeURIComponent(job)}`),
  answer: (job: string) => get<AnswerResponse>(`/api/answer?job=${encodeURIComponent(job)}`),
  overview: () => get<Overview>("/api/overview"),
  rubric: () => get<Rubric>("/api/rubric"),
};

export interface Peek { query: string; engine: EngineKey; cached: boolean; cost: 0 | 1; can_run: boolean; session_left: number }
export interface Suggestion { q: string; cached: boolean }

export const live = {
  peek: (q: string, engine: EngineKey, signal?: AbortSignal) =>
    fetch(`/api/peek?q=${encodeURIComponent(q)}&engine=${engine}`, { signal }).then((r) => (r.ok ? (r.json() as Promise<Peek>) : null)),
  suggest: (q: string, engine: EngineKey, signal?: AbortSignal) =>
    fetch(`/api/suggest?q=${encodeURIComponent(q)}&engine=${engine}`, { signal })
      .then((r) => (r.ok ? r.json() : { suggestions: [] }))
      .then((d: { suggestions: Suggestion[] }) => d.suggestions),
};
