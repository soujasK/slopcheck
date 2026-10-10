import * as Tabs from "@radix-ui/react-tabs";
import { Moon, Sun } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "./components/ui/button";
import { Tooltip, TooltipProvider } from "./components/ui/tooltip";
import { api, type Rubric } from "./lib/api";
import { protectiveMatchers, store } from "./lib/utils";
import { MethodView } from "./views/MethodView";
import { ObservatoryView } from "./views/ObservatoryView";
import { SearchView } from "./views/SearchView";

type View = "search" | "overview" | "method";
const VIEWS: { value: View; label: string }[] = [
  { value: "search", label: "Live search" },
  { value: "overview", label: "Observatory" },
  { value: "method", label: "Method" },
];

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="size-[40px]" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#1c1b18" />
      <circle cx="14" cy="14" r="7" fill="none" stroke="#3cc0a8" strokeWidth="3" />
      <path d="m19 19 6 6" stroke="#d0794c" strokeWidth="3.4" strokeLinecap="round" />
    </svg>
  );
}

const fromHash = (): View => {
  const h = location.hash.slice(1);
  return VIEWS.some((v) => v.value === h) ? (h as View) : "search";
};

export default function App() {
  const [view, setView] = useState<View>(fromHash);
  const [dark, setDark] = useState(() => {
    const t = store<string>("sw-theme");
    return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  });
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [credits, setCredits] = useState<{ session_spent: number; session_cap: number } | null>(null);
  const [focusSignal, setFocusSignal] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [mood, setMood] = useState<"idle" | "clean" | "slop">("idle");

  useEffect(() => { api.rubric().then(setRubric).catch(() => {}); }, []);
  const matchers = useMemo(() => protectiveMatchers(rubric?.rules ?? []), [rubric]);
  const isProtective = useCallback((why: string) => matchers.some((re) => re.test(why)), [matchers]);

  const changeView = (v: View) => {
    setView(v);
    try { history.replaceState(null, "", `${location.search}#${v}`); } catch { /* ignore */ }
  };
  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    store("sw-theme", next ? "dark" : "light");
  };
  const flash = useCallback((m: string) => { setToast(m); setTimeout(() => setToast(null), 1800); }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement as HTMLElement | null)?.tagName ?? "");
      if (e.key === "/" && !typing) { e.preventDefault(); changeView("search"); setFocusSignal((n) => n + 1); }
      if (e.key === "Escape" && typing) (document.activeElement as HTMLElement).blur();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <TooltipProvider>
      {/* ambient glow that follows the live result: teal when the agent's top 5 is clean, ochre when slop was in it */}
      <motion.div aria-hidden="true" className="pointer-events-none fixed inset-x-0 top-0 -z-10 h-[520px]"
        animate={{ opacity: view === "search" && mood !== "idle" ? 1 : 0.55,
          background: `radial-gradient(60% 70% at 50% -10%, color-mix(in srgb, ${mood === "slop" ? "var(--risk)" : "var(--clean)"} ${mood === "idle" ? 7 : 16}%, transparent), transparent 70%)` }}
        transition={{ duration: 0.9 }} />
      <Tabs.Root value={view} onValueChange={(v) => changeView(v as View)} className="relative min-h-screen">
        <header className="mx-auto max-w-[1240px] px-4 pt-3 md:px-6">
          {/* dateline */}
          <div className="flex flex-wrap items-center justify-between gap-2 pb-2 font-mono text-[0.66rem] uppercase tracking-[0.16em] text-ink-3">
            <span>Knowledge &amp; public interest · India edition</span>
            <span className="hidden sm:inline">{new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</span>
          </div>
          {/* masthead */}
          <div className="rule-double flex flex-wrap items-end gap-x-6 gap-y-3 pt-3.5 pb-3">
            <a href="#search" onClick={(e) => { e.preventDefault(); changeView("search"); }} className="flex items-center gap-3" aria-label="SlopWatch home">
              <Logo />
              <span className="leading-none">
                <b className="block font-display text-[2rem] font-semibold tracking-[-0.01em]">Slop<span className="text-risk">Watch</span></b>
                <i className="mt-1 block font-display text-[0.98rem] text-ink-2">The agent's reading desk</i>
              </span>
            </a>
            <div className="ml-auto flex items-center gap-2">
              {credits && (
                <Tooltip content="SerpApi credits used this session. Repeated questions come from the cache for free.">
                  <span tabIndex={0} className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-2.5 py-1 font-mono text-[0.72rem] text-ink-2">
                    <span className="size-1.5 rounded-full bg-clean" />{credits.session_spent} / {credits.session_cap} credits
                  </span>
                </Tooltip>
              )}
              <Tooltip content={dark ? "Light theme" : "Dark theme"}>
                <Button variant="outline" size="icon" onClick={toggleTheme} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
                  {dark ? <Sun className="size-[17px]" /> : <Moon className="size-[17px]" />}
                </Button>
              </Tooltip>
            </div>
          </div>
          {/* sections */}
          <Tabs.List aria-label="Sections" className="rule-hair flex gap-6 border-b border-line-2">
            {VIEWS.map((v) => (
              <Tabs.Trigger key={v.value} value={v.value} className="relative cursor-pointer py-2.5 font-mono text-[0.74rem] font-medium uppercase tracking-[0.14em] text-ink-3 transition-colors hover:text-ink data-[state=active]:text-ink">
                {v.label}
                {view === v.value && <motion.span layoutId="nav-rule" className="absolute inset-x-0 -bottom-px h-[2px] bg-ink" transition={{ type: "spring", bounce: 0.15, duration: 0.4 }} />}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
        </header>

        <main className="mx-auto max-w-[1240px] px-4 pb-16 pt-6 md:px-6 md:pt-8">
          <Tabs.Content value="search" forceMount hidden={view !== "search"} className="outline-none">
            <SearchView isProtective={isProtective} onCredits={setCredits} onMood={setMood} focusSignal={focusSignal} toast={flash} />
          </Tabs.Content>
          <Tabs.Content value="overview" className="outline-none">
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}><ObservatoryView /></motion.div>
          </Tabs.Content>
          <Tabs.Content value="method" className="outline-none">
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}><MethodView rubric={rubric} /></motion.div>
          </Tabs.Content>
        </main>

        <footer className="mx-auto flex max-w-[1240px] flex-wrap justify-between gap-3 px-4 pb-10 font-mono text-[0.74rem] text-ink-3 md:px-6">
          <span>Built on SerpApi · deterministic signals, no AI-text detection</span>
        </footer>
      </Tabs.Root>

      <AnimatePresence>
        {toast && (
          <motion.div role="status" initial={{ opacity: 0, y: 8, x: "-50%" }} animate={{ opacity: 1, y: 0, x: "-50%" }} exit={{ opacity: 0, y: 8, x: "-50%" }}
            className="fixed bottom-5 left-1/2 z-50 rounded-xl bg-ink px-4 py-2.5 text-[0.85rem] text-surface shadow-elev">{toast}</motion.div>
        )}
      </AnimatePresence>
    </TooltipProvider>
  );
}
