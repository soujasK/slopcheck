import { AlertTriangle, ArrowDownWideNarrow, Copy, Equal, GitCompareArrows, Info, ListOrdered, RotateCcw, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AnswerCard, AnswerSkeleton } from "../components/AnswerCard";
import { Composer } from "../components/Composer";
import { Pipeline } from "../components/Pipeline";
import { ResultRow, ResultSkeleton } from "../components/ResultRow";
import { VerdictBar, type Filter } from "../components/VerdictBar";
import { Button } from "../components/ui/button";
import { Card, CardHeader, Stat } from "../components/ui/card";
import { Segmented } from "../components/ui/segmented";
import { Tooltip } from "../components/ui/tooltip";
import type { EngineKey } from "../lib/api";
import { wordDiff } from "../lib/diff";
import { useSearchRun } from "../lib/useSearchRun";
import { ENGINES, clean, cn, engineName, host, store, verdict } from "../lib/utils";

const EXAMPLES = ["how to improve cibil score fast", "best smartphone under 20000", "best water purifier for home ro or uv"];
type Recent = { q: string; engine: EngineKey };
type Sort = "rank" | "risk";

export function SearchView({ isProtective, onCredits, onMood, focusSignal, toast }: {
  isProtective: (why: string) => boolean;
  onCredits: (c: { session_spent: number; session_cap: number } | null) => void;
  onMood: (m: "idle" | "clean" | "slop") => void;
  focusSignal: number;
  toast: (m: string) => void;
}) {
  const { state, run } = useSearchRun();
  const [q, setQ] = useState("");
  const [engine, setEngine] = useState<EngineKey>("google-in");
  const [recent, setRecent] = useState<Recent[]>(() => store<Recent[]>("sw-recent") ?? []);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("rank");
  const [whatIf, setWhatIf] = useState<number | null>(null);
  const [showDiff, setShowDiff] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  const busy = state.phase !== "idle" && state.phase !== "done" && !state.error;

  useEffect(() => { onCredits(state.credits); }, [state.credits, onCredits]);
  useEffect(() => { input.current?.focus(); }, [focusSignal]);

  const go = (query: string, eng: EngineKey) => {
    const text = clean(query);
    if (!text || busy) return;
    setQ(text); setEngine(eng); setFilter("all"); setSort("rank"); setWhatIf(null);
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

  const frozen = state.threshold;           // the line the agent comparison uses
  const line = whatIf ?? frozen;            // the line the result list shows
  const verdicts = state.results.map((r) => verdict(state.scores[r.link], line));

  const stats = useMemo(() => {
    const risks = state.results.map((r) => state.scores[r.link]?.slop_risk).filter((x): x is number => x != null).sort((a, b) => a - b);
    const m = Math.floor(risks.length / 2);
    return {
      read: state.results.filter((r) => state.scores[r.link]).length,
      scored: risks.length,
      median: risks.length ? (risks.length % 2 ? risks[m] : (risks[m - 1] + risks[m]) / 2) : null,
      slop: verdicts.filter((v) => v === "slop").length,
      slopTop5: verdicts.slice(0, 5).filter((v) => v === "slop").length,
      frozenSlop: state.results.filter((r) => verdict(state.scores[r.link], frozen) === "slop").length,
    };
  }, [state.results, state.scores, line, frozen]);

  // page mood follows the outcome: teal glow when the agent's top 5 is clean, ochre when slop was in it
  useEffect(() => {
    if (state.phase === "idle" || !state.results.length || stats.read < Math.min(5, state.results.length)) onMood("idle");
    else onMood(state.results.slice(0, 5).some((r) => verdict(state.scores[r.link], frozen) === "slop") ? "slop" : "clean");
  }, [state.phase, state.results, state.scores, stats.read, frozen, onMood]);

  const a = state.answers;
  const citedSet = (x: { cited: { link: string }[] }) => x.cited.map((c) => c.link).sort().join("|");
  const tainted = !!a && a.before.cited.some((c) => verdict(state.scores[c.link], frozen) === "slop");
  const diff = useMemo(() => (a && !a.same_sources ? wordDiff(a.before.answer, a.after.answer) : null), [a]);

  const shown = useMemo(() => {
    const rows = state.results.map((r, i) => ({ r, v: verdicts[i] })).filter(({ v }) =>
      filter === "all" || (filter === "slop" && v === "slop") || (filter === "clear" && (v === "clear" || v === "borderline")) ||
      (filter === "other" && (v === "platform" || v === "unreadable")));
    if (sort === "risk") rows.sort((x, y) => (state.scores[y.r.link]?.slop_risk ?? -1) - (state.scores[x.r.link]?.slop_risk ?? -1));
    return rows.map(({ r }) => r);
  }, [state.results, state.scores, verdicts, filter, sort]);

  const copy = async () => {
    const payload = { query: state.query, engine: state.engine, threshold: frozen, results: state.results.map((r) => ({ ...r, slopwatch: state.scores[r.link] ?? null })), answers: a };
    try { await navigator.clipboard.writeText(JSON.stringify(payload, null, 2)); toast("Copied run as JSON"); } catch { toast("Clipboard unavailable"); }
  };

  return (
    <div className="grid gap-5">
      <header>
        <p className="eyebrow m-0">Live search · SerpApi</p>
        <h1 className="mt-1.5 font-display text-[clamp(1.8rem,3.6vw,2.7rem)] font-bold leading-[1.05] tracking-[-0.03em] text-balance">
          <motion.span key={state.query || "idle"} className="inline-block" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
            {state.query ? <>What your agent reads for <span className="text-clean-ink">“{state.query}”</span></> : "What will your agent read?"}
          </motion.span>
        </h1>
        <p className="mt-2 max-w-[46rem] text-[1rem] text-ink-2">
          {state.query ? `${engineName(state.engine)} · every result read and scored on transparent signals, then the same agent answers with and without the slop.`
            : "Ask any question. SlopWatch fetches the real results, reads every page, scores it on transparent signals, and shows the agent's answer with and without the slop."}
        </p>
      </header>

      <Composer q={q} setQ={setQ} engine={engine} setEngine={setEngine} busy={busy} onRun={go} inputRef={input} examples={EXAMPLES} recent={recent} />

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
            { title: "Score", detail: `${stats.frozenSlop} flagged at risk ≥ ${frozen.toFixed(2)}` },
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
              <Stat label={whatIf != null ? "Flagged at your line" : "Flagged as slop"} value={<motion.span key={stats.slop} initial={{ scale: 1.15 }} animate={{ scale: 1 }} className="inline-block">{stats.slop}</motion.span>} tone="risk" hint={`${stats.slopTop5} in the top 5 the agent reads`} />
              <Stat label="Median slop risk" value={stats.median == null ? "–" : stats.median.toFixed(2)} hint={`slop line at ${line.toFixed(2)} · ${stats.scored} scored`} />
            </div>
          )}

          {a && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
              className={cn("flex flex-wrap items-start gap-3.5 rounded-2xl border px-5 py-4", a.same_sources ? "border-info/25 bg-info-soft" : "border-clean/35 bg-clean-soft")}>
              {a.same_sources ? <Equal className="mt-0.5 size-[22px] shrink-0 text-info" /> : <ShieldCheck className="mt-0.5 size-[22px] shrink-0 text-clean-ink" />}
              <div className="min-w-0 flex-1">
                <b className="block text-[1rem]">{a.same_sources ? "Top 5 was clean: nothing removed" : `SlopWatch removed ${a.dropped.length} of the top 5 before the agent read them`}</b>
                <p className="m-0 mt-0.5 text-[0.88rem] text-ink-2">
                  {a.same_sources
                    ? "Both answers come from the same five sources, so they are identical by construction."
                    : `Removed: ${a.dropped.map(host).join(", ")}. ${citedSet(a.before) !== citedSet(a.after) ? "The filtered agent cites different sources." : "The cited sources did not change."}${tainted ? " The unfiltered answer cited a flagged page." : ""}${diff ? ` ${diff.changed} word(s) differ between the answers.` : ""}`}
                </p>
              </div>
              {diff && diff.changed > 0 && (
                <Button variant="outline" size="sm" aria-pressed={showDiff} onClick={() => setShowDiff((d) => !d)}><GitCompareArrows className="size-3.5" />{showDiff ? "Hide differences" : "Show differences"}</Button>
              )}
            </motion.div>
          )}
          {(a || state.phase === "answering") && (
            <div className="grid gap-4 lg:grid-cols-2">
              {a ? <AnswerCard a={a.before} scores={state.scores} threshold={frozen} filtered={false} tainted={tainted} diff={showDiff ? diff?.a : null} /> : <AnswerSkeleton filtered={false} />}
              {a ? <AnswerCard a={a.after} scores={state.scores} threshold={frozen} filtered diff={showDiff ? diff?.b : null} /> : <AnswerSkeleton filtered />}
            </div>
          )}

          {(state.results.length > 0 || state.phase === "searching") && (
            <Card>
              <CardHeader
                title={<>Search results <span className="font-mono text-[0.74rem] font-normal text-ink-3">{shown.length !== state.results.length ? `${shown.length} of ${state.results.length} shown` : ""}</span></>}
                aside={<>
                  <Segmented label="Sort results" value={sort} onChange={setSort} options={[{ value: "rank", label: "Rank" }, { value: "risk", label: "Risk" }]} />
                  <Tooltip content={sort === "rank" ? "as the engine ranked them" : "highest slop risk first"}><span className="text-ink-3">{sort === "rank" ? <ListOrdered className="size-4" /> : <ArrowDownWideNarrow className="size-4" />}</span></Tooltip>
                  <Button variant="outline" size="sm" disabled={!state.results.length} onClick={copy}><Copy className="size-3.5" />Copy JSON</Button>
                </>}
              />
              {state.results.length > 0 && (
                <div className="grid gap-4 border-b border-line px-5 py-4 md:grid-cols-[minmax(0,1fr)_18rem] md:items-start">
                  <VerdictBar verdicts={verdicts} filter={filter} onFilter={setFilter} />
                  <div className="grid gap-1.5 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <label htmlFor="whatif" className="inline-flex items-center gap-1.5 text-[0.8rem] font-medium"><SlidersHorizontal className="size-3.5 text-ink-3" />What-if slop line</label>
                      <span className="font-mono text-[0.78rem] tabular">{line.toFixed(2)}{whatIf != null && whatIf !== frozen && <button type="button" onClick={() => setWhatIf(null)} className="ml-2 inline-flex cursor-pointer items-center gap-1 text-ink-3 hover:text-ink" aria-label="Reset to the frozen line"><RotateCcw className="size-3" />{frozen.toFixed(2)}</button>}</span>
                    </div>
                    <input id="whatif" type="range" min={0.2} max={0.8} step={0.01} value={line} onChange={(e) => setWhatIf(Number(e.target.value))} className="w-full accent-[var(--risk)]" />
                    <p className="m-0 font-mono text-[0.68rem] text-ink-3">{whatIf != null && whatIf !== frozen ? `${stats.slop} flagged here vs ${stats.frozenSlop} at the frozen line. The agent comparison always uses the frozen ${frozen.toFixed(2)}.` : "Drag to see how a stricter or looser line changes what is flagged."}</p>
                  </div>
                </div>
              )}
              <ul className="m-0 list-none p-0">
                {state.phase === "searching" ? <ResultSkeleton /> : (
                  <AnimatePresence initial={false}>
                    {shown.map((r) => <ResultRow key={r.link} r={r} s={state.scores[r.link]} threshold={line} isProtective={isProtective} />)}
                  </AnimatePresence>
                )}
                {state.phase !== "searching" && !shown.length && <li className="px-5 py-6 text-center font-mono text-[0.8rem] text-ink-3">No results in this filter.</li>}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
