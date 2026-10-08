import { CircleDollarSign, Compass, FlaskConical, Search, Sparkles, X, Zap } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { live, type EngineKey, type Peek, type Suggestion } from "../lib/api";
import { guessTopic } from "../lib/topic";
import { ENGINES, clean, cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Segmented } from "./ui/segmented";

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/** Bold the parts of a suggestion that match the typed words. */
function highlight(text: string, typed: string): ReactNode {
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);
  return text.split(/(\s+)/).map((tok, i) => {
    const w = words.find((x) => tok.toLowerCase().startsWith(x));
    return w ? <span key={i}><b className="font-semibold text-ink">{tok.slice(0, w.length)}</b>{tok.slice(w.length)}</span> : <span key={i}>{tok}</span>;
  });
}

export function Composer({ q, setQ, engine, setEngine, busy, onRun, inputRef, examples, recent }: {
  q: string; setQ: (v: string) => void; engine: EngineKey; setEngine: (e: EngineKey) => void; busy: boolean;
  onRun: (q: string, e: EngineKey) => void; inputRef: React.RefObject<HTMLInputElement | null>;
  examples: string[]; recent: { q: string; engine: EngineKey }[];
}) {
  const listId = useId();
  const [focused, setFocused] = useState(false);
  const [sugs, setSugs] = useState<Suggestion[]>([]);
  const [active, setActive] = useState(-1);
  const [peek, setPeek] = useState<Peek | null>(null);
  const typed = clean(q);
  const dq = useDebounced(typed, 220);
  const topic = guessTopic(typed);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    abort.current?.abort();
    if (!dq || busy) { setSugs([]); setPeek(null); return; }
    const ctl = new AbortController(); abort.current = ctl;
    Promise.all([live.peek(dq, engine, ctl.signal), live.suggest(dq, engine, ctl.signal)])
      .then(([p, s]) => { setPeek(p); setSugs(s.filter((x) => x.q.toLowerCase() !== dq.toLowerCase())); setActive(-1); })
      .catch(() => { /* aborted or server busy: keep the last state */ });
    return () => ctl.abort();
  }, [dq, engine, busy]);

  const open = focused && sugs.length > 0 && !busy;
  const pick = (s: string) => { setQ(s); setSugs([]); onRun(s, engine); };
  const stale = peek && peek.query.toLowerCase() !== typed.toLowerCase();

  return (
    <Card className="relative grid gap-3.5 p-4 shadow-elev">
      <form className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={(e) => { e.preventDefault(); if (active >= 0 && open) pick(sugs[active].q); else onRun(q, engine); }}>
        <div className="relative min-w-0">
          <label className={cn("flex min-w-0 items-center gap-3 rounded-xl border-[1.5px] border-line bg-surface-2 px-4 transition-[border-color,box-shadow]",
            "focus-within:border-clean focus-within:shadow-[0_0_0_4px_color-mix(in_srgb,var(--clean)_16%,transparent)]", open && "rounded-b-none")}>
            <Search className="size-5 shrink-0 text-ink-3" />
            <span className="sr-only">Question</span>
            <input
              ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} type="text" maxLength={200} required autoComplete="off"
              role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
              aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
              onFocus={() => setFocused(true)} onBlur={() => setTimeout(() => setFocused(false), 120)}
              onKeyDown={(e) => {
                if (!open) return;
                if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % sugs.length); }
                if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a <= 0 ? sugs.length - 1 : a - 1)); }
                if (e.key === "Escape") { setSugs([]); }
              }}
              placeholder="e.g. how to get money back after online fraud"
              className="min-w-0 flex-1 bg-transparent py-3.5 text-[1.05rem] outline-none placeholder:text-ink-3"
            />
            {q && <button type="button" aria-label="Clear" onClick={() => { setQ(""); inputRef.current?.focus(); }} className="grid size-6 cursor-pointer place-items-center rounded-md text-ink-3 hover:bg-surface-3 hover:text-ink"><X className="size-4" /></button>}
            <kbd className="rounded-md border border-b-2 border-line-2 px-1.5 font-mono text-[0.7rem] text-ink-3" aria-hidden="true">/</kbd>
          </label>
          <AnimatePresence>
            {open && (
              <motion.ul id={listId} role="listbox" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.12 }}
                className="absolute inset-x-0 top-full z-20 m-0 list-none overflow-hidden rounded-b-xl border-[1.5px] border-t-0 border-clean bg-surface p-1 shadow-elev">
                {sugs.map((s, i) => (
                  <li key={s.q} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                    onMouseDown={(e) => { e.preventDefault(); pick(s.q); }} onMouseEnter={() => setActive(i)}
                    className={cn("flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-[0.92rem] text-ink-2", i === active && "bg-surface-3")}>
                    <Search className="size-4 shrink-0 text-ink-3" />
                    <span className="min-w-0 flex-1 truncate">{highlight(s.q, typed)}</span>
                    {s.cached
                      ? <span className="inline-flex items-center gap-1 font-mono text-[0.66rem] font-semibold uppercase tracking-wider text-clean-ink"><Zap className="size-3" />cached · free</span>
                      : <span className="font-mono text-[0.66rem] uppercase tracking-wider text-ink-3">1 credit</span>}
                  </li>
                ))}
              </motion.ul>
            )}
          </AnimatePresence>
        </div>
        <Button size="lg" type="submit" disabled={busy || (!!peek && !stale && !peek.can_run)}>{busy ? "Working…" : "Analyze results"}</Button>
      </form>

      {/* live read-out of what this question will do, before it is run */}
      <div className="flex min-h-7 flex-wrap items-center gap-2" aria-live="polite">
        <AnimatePresence initial={false}>
          {typed && peek && !stale && (
            <motion.span key={`cost-${peek.cached}-${peek.can_run}`} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
              className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[0.72rem]",
                peek.cached ? "bg-clean-soft text-clean-ink" : peek.can_run ? "bg-surface-3 text-ink-2" : "bg-risk-soft text-risk-ink")}>
              {peek.cached ? <><Zap className="size-3.5" />cached · runs free</> : peek.can_run ? <><CircleDollarSign className="size-3.5" />new search · 1 SerpApi credit · {peek.session_left} left this session</> : <>session credit cap reached · restart with --max-credits</>}
            </motion.span>
          )}
          {topic && (
            <motion.span key={`topic-${topic.id}`} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}
              className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[0.72rem]", topic.validated ? "bg-surface-3 text-ink-2" : "bg-info-soft text-info")}
              title={topic.validated ? "SlopWatch's rubric was fitted and tested on this topic" : "Outside the four topics the rubric was fitted on. Tested once on these topics (round 5): precision 0.56, below the 0.70 bar, so treat flags here as a weaker signal"}>
              {topic.validated ? <Compass className="size-3.5" /> : <FlaskConical className="size-3.5" />}
              looks like {topic.label}{topic.validated ? " · validated topic" : " · tested, weaker signal here"}
            </motion.span>
          )}
          {typed && !peek && !topic && (
            <motion.span key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="inline-flex items-center gap-1.5 font-mono text-[0.72rem] text-ink-3"><Sparkles className="size-3.5" />checking the cache…</motion.span>
          )}
        </AnimatePresence>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented label="Search engine" value={engine} onChange={setEngine} options={ENGINES.map((e) => ({ value: e.key, label: e.name }))} />
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[0.8rem] text-ink-3">Try</span>
          {examples.map((ex) => (
            <Button key={ex} variant="chip" size="chip" disabled={busy} onClick={() => { setQ(ex); onRun(ex, "google-in"); }}>
              {ex}<span className="font-mono text-[0.6rem] font-semibold uppercase tracking-wider text-clean-ink">cached</span>
            </Button>
          ))}
        </div>
      </div>
      {recent.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[0.8rem] text-ink-3">Recent</span>
          {recent.map((r) => <Button key={r.q + r.engine} variant="chip" size="chip" disabled={busy} onClick={() => { setQ(r.q); onRun(r.q, r.engine); }}>{r.q}</Button>)}
        </div>
      )}
    </Card>
  );
}
