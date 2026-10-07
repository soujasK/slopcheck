import { AlertTriangle, Copy, Equal, Eye, EyeOff, Info, Search, ShieldCheck } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AnswerCard, AnswerSkeleton } from "../components/AnswerCard";
import { Pipeline } from "../components/Pipeline";
import { ResultRow, ResultSkeleton } from "../components/ResultRow";
import { Button } from "../components/ui/button";
import { Card, CardHeader, Stat } from "../components/ui/card";
import { Segmented } from "../components/ui/segmented";
import type { EngineKey } from "../lib/api";
import { useSearchRun } from "../lib/useSearchRun";
import { ENGINES, clean, cn, engineName, host, store, verdict } from "../lib/utils";

const EXAMPLES = ["how to improve cibil score fast", "best smartphone under 20000", "best water purifier for home ro or uv"];
type Recent = { q: string; engine: EngineKey };

export function SearchView({ isProtective, onCredits, focusSignal, toast }: {
  isProtective: (why: string) => boolean;
  onCredits: (c: { session_spent: number; session_cap: number } | null) => void;
  focusSignal: number;
  toast: (m: string) => void;
}) {
  const { state, run } = useSearchRun();
  const [q, setQ] = useState("");
  const [engine, setEngine] = useState<EngineKey>("google-in");
  const [hideSlop, setHideSlop] = useState(false);
  const [recent, setRecent] = useState<Recent[]>(() => store<Recent[]>("sw-recent") ?? []);
  const input = useRef<HTMLInputElement>(null);
  const busy = state.phase !== "idle" && state.phase !== "done" && !state.error;

  useEffect(() => { onCredits(state.credits); }, [state.credits, onCredits]);
  useEffect(() => { input.current?.focus(); }, [focusSignal]);

  const go = (query: string, eng: EngineKey) => {
    const text = clean(query);
    if (!text || busy) return;
    setQ(text); setEngine(eng); setHideSlop(false);
    const next = [{ q: text, engine: eng }, ...recent.filter((r) => !(r.q === text && r.engine === eng))].slice(0, 5);
    setRecent(next); store("sw-recent", next);
    try { history.replaceState(null, "", `?q=${encodeURIComponent(text)}&engine=${eng}#search`); } catch { /* ignore */ }
    void run(text, eng);
  };

  // shareable links: /?q=...&engine=... runs on load
  useEffect(() => {
    const p = new URLSearchParams(location.search);
    const q0 = p.get("q");
    const e0 = p.get("engine") as EngineKey | null;
    if (q0) go(q0, e0 && ENGINES.some((e) => e.key === e0) ? e0 : "google-in");
  }, []);

  const t = state.threshold;
  const stats = useMemo(() => {
    const risks = state.results.map((r) => state.scores[r.link]?.slop_risk).filter((x): x is number => x != null).sort((a, b) => a - b);
    const m = Math.floor(risks.length / 2);
    const slop = state.results.filter((r) => verdict(state.scores[r.link], t) === "slop");
    return {
      read: state.results.filter((r) => state.scores[r.link]).length,
      scored: risks.length,
      median: risks.length ? (risks.length % 2 ? risks[m] : (risks[m - 1] + risks[m]) / 2) : null,
      slop: slop.length,
      slopTop5: state.results.slice(0, 5).filter((r) => verdict(state.scores[r.link], t) === "slop").length,
    };
  }, [state.results, state.scores, t]);

  const a = state.answers;
  const citedSet = (x: { cited: { link: string }[] }) => x.cited.map((c) => c.link).sort().join("|");
  const tainted = !!a && a.before.cited.some((c) => verdict(state.scores[c.link], t) === "slop");
  const shown = hideSlop ? state.results.filter((r) => verdict(state.scores[r.link], t) !== "slop") : state.results;

  const copy = async () => {
    const payload = { query: state.query, engine: state.engine, threshold: t, results: state.results.map((r) => ({ ...r, slopwatch: state.scores[r.link] ?? null })), answers: a };
    try { await navigator.clipboard.writeText(JSON.stringify(payload, null, 2)); toast("Copied run as JSON"); } catch { toast("Clipboard unavailable"); }
  };

  return (
    <div className="grid gap-5">
      <header>
        <p className="eyebrow m-0">Live search · SerpApi</p>
        <h1 className="mt-1.5 font-display text-[clamp(1.8rem,3.6vw,2.7rem)] font-bold leading-[1.05] tracking-[-0.03em] text-balance">What will your agent read?</h1>
        <p className="mt-2 max-w-[46rem] text-[1rem] text-ink-2">Ask any question. SlopWatch fetches the real results, reads every page, scores it on transparent signals, and shows the agent's answer with and without the slop.</p>
      </header>

      <Card className="grid gap-3.5 p-4 shadow-elev">
        <form className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={(e) => { e.preventDefault(); go(q, engine); }}>
          <label className="flex min-w-0 items-center gap-3 rounded-xl border-[1.5px] border-line bg-surface-2 px-4 transition-[border-color,box-shadow] focus-within:border-clean focus-within:shadow-[0_0_0_4px_color-mix(in_srgb,var(--clean)_16%,transparent)]">
            <Search className="size-5 shrink-0 text-ink-3" />
            <span className="sr-only">Question</span>
            <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} type="search" maxLength={200} required autoComplete="off"
              placeholder="e.g. how to get money back after online fraud" className="min-w-0 flex-1 bg-transparent py-3.5 text-[1.05rem] outline-none placeholder:text-ink-3" />
            <kbd className="rounded-md border border-b-2 border-line-2 px-1.5 font-mono text-[0.7rem] text-ink-3" aria-hidden="true">/</kbd>
          </label>
          <Button size="lg" type="submit" disabled={busy}>{busy ? "Working…" : "Analyze results"}</Button>
        </form>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented label="Search engine" value={engine} onChange={setEngine} options={ENGINES.map((e) => ({ value: e.key, label: e.name }))} />
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[0.8rem] text-ink-3">Try</span>
            {EXAMPLES.map((ex) => (
              <Button key={ex} variant="chip" size="chip" disabled={busy} onClick={() => go(ex, "google-in")}>
                {ex}<span className="font-mono text-[0.6rem] font-semibold uppercase tracking-wider text-clean-ink">cached</span>
              </Button>
            ))}
          </div>
        </div>
        {recent.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[0.8rem] text-ink-3">Recent</span>
            {recent.map((r) => <Button key={r.q + r.engine} variant="chip" size="chip" disabled={busy} onClick={() => go(r.q, r.engine)}>{r.q}{r.engine !== "google-in" && <span className="text-ink-3">· {engineName(r.engine)}</span>}</Button>)}
          </div>
        )}
      </Card>

      {state.phase === "idle" ? (
        <Card className="grid gap-6 p-6 md:grid-cols-3">
          {[
            ["01 · Search", "Real results through SerpApi", "Google, DuckDuckGo or Yahoo, India or US: exactly what an agent's search tool returns. Repeated questions come from the cache for free."],
            ["02 · Read and score", "Every page, transparent signals", "Author and date, whether the page answers the question, selling, ads, thin text. A weighted rule set, fitted and frozen; no AI judges a page."],
            ["03 · Compare", "The same agent, twice", "Once from the raw top 5 and once with slop removed. Every citation is marked, so you see exactly what changed."],
          ].map(([n, h, p]) => (
            <div key={n} className="grid content-start gap-1.5"><span className="font-mono text-[0.74rem] font-semibold uppercase text-clean-ink">{n}</span><b className="text-[0.96rem]">{h}</b><p className="m-0 text-[0.86rem] text-ink-2">{p}</p></div>
          ))}
        </Card>
      ) : (
        <>
          <Pipeline phase={state.phase} error={!!state.error} agentOn={state.agentOn} steps={[
            { title: "Search", detail: state.results.length ? `${state.results.length} results · ${state.cached ? "cached, free" : "1 credit"}` : `SerpApi · ${engineName(state.engine)}` },
            { title: "Read pages", detail: `${stats.read} / ${state.results.length || "–"} fetched, robots-aware` },
            { title: "Score", detail: `${stats.slop} flagged at risk ≥ ${t.toFixed(2)}` },
            { title: "Agent answers", detail: !state.agentOn && state.phase !== "searching" ? "off: set GEMINI_API_KEY" : a ? "raw vs filtered, compared" : "raw vs filtered top 5" },
          ]} />

          <AnimatePresence>
            {state.error && (
              <motion.div role="alert" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="flex items-start gap-3 rounded-xl bg-risk-soft px-4 py-3 text-[0.88rem] text-risk-ink">
                <AlertTriangle className="mt-0.5 size-[18px] shrink-0" />{state.error}
              </motion.div>
            )}
          </AnimatePresence>
          {state.phase === "done" && !state.agentOn && (
            <div className="flex items-start gap-3 rounded-xl bg-info-soft px-4 py-3 text-[0.88rem] text-info"><Info className="mt-0.5 size-[18px] shrink-0" />Agent answers are off. Set GEMINI_API_KEY in .env and restart <code className="font-mono">slopwatch serve</code> to compare answers.</div>
          )}

          {state.results.length > 0 && (
            <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(12.5rem,1fr))]">
              <Stat label="Results" value={state.results.length} hint={`${engineName(state.engine)} · ${state.cached ? "from cache, 0 credits" : "1 credit"}`} />
              <Stat label="Pages read" value={`${stats.read} / ${state.results.length}`}>
                <span className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-3"><motion.b className="block h-full rounded-full bg-clean" animate={{ width: `${(stats.read / state.results.length) * 100}%` }} /></span>
              </Stat>
              <Stat label="Flagged as slop" value={stats.slop} tone="risk" hint={`${stats.slopTop5} in the top 5 the agent reads`} />
              <Stat label="Median slop risk" value={stats.median == null ? "–" : stats.median.toFixed(2)} hint={`slop line at ${t.toFixed(2)} · ${stats.scored} scored`} />
            </div>
          )}

          {a && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className={cn("flex items-start gap-3.5 rounded-2xl border px-5 py-4", a.same_sources ? "border-info/25 bg-info-soft" : "border-clean/35 bg-clean-soft")}>
              {a.same_sources ? <Equal className="mt-0.5 size-[22px] shrink-0 text-info" /> : <ShieldCheck className="mt-0.5 size-[22px] shrink-0 text-clean-ink" />}
              <div>
                <b className="block text-[1rem]">{a.same_sources ? "Top 5 was clean: nothing removed" : `SlopWatch removed ${a.dropped.length} of the top 5 before the agent read them`}</b>
                <p className="m-0 mt-0.5 text-[0.88rem] text-ink-2">
                  {a.same_sources
                    ? "Both answers come from the same five sources, so they are identical by construction."
                    : `Removed: ${a.dropped.map(host).join(", ")}. ${citedSet(a.before) !== citedSet(a.after) ? "The filtered agent cites different sources." : "The cited sources did not change."}${tainted ? " The unfiltered answer cited a flagged page." : ""}`}
                </p>
              </div>
            </motion.div>
          )}
          {(a || state.phase === "answering") && (
            <div className="grid gap-4 lg:grid-cols-2">
              {a ? <AnswerCard a={a.before} scores={state.scores} threshold={t} filtered={false} tainted={tainted} /> : <AnswerSkeleton filtered={false} />}
              {a ? <AnswerCard a={a.after} scores={state.scores} threshold={t} filtered /> : <AnswerSkeleton filtered />}
            </div>
          )}

          {(state.results.length > 0 || state.phase === "searching") && (
            <Card>
              <CardHeader
                title={<>Search results <span className="font-mono text-[0.74rem] font-normal text-ink-3">“{state.query}”</span></>}
                aside={<>
                  <Button variant="outline" size="sm" disabled={!stats.slop} aria-pressed={hideSlop} onClick={() => setHideSlop((h) => !h)}>{hideSlop ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}{hideSlop ? "Show flagged" : "Hide flagged"}</Button>
                  <Button variant="outline" size="sm" disabled={!state.results.length} onClick={copy}><Copy className="size-3.5" />Copy JSON</Button>
                </>}
              />
              <ul className="m-0 list-none p-0">
                {state.phase === "searching" ? <ResultSkeleton /> : (
                  <AnimatePresence initial={false}>
                    {shown.map((r) => <ResultRow key={r.link} r={r} s={state.scores[r.link]} threshold={t} isProtective={isProtective} />)}
                  </AnimatePresence>
                )}
              </ul>
              {hideSlop && stats.slop > 0 && <div className="border-t border-line px-5 py-3 font-mono text-[0.76rem] text-ink-3">{stats.slop} flagged result(s) hidden. They never reach the filtered agent.</div>}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
