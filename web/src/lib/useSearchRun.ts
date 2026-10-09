import { useCallback, useRef, useState } from "react";
import { api, ApiError, type AnswerResponse, type Assessment, type Credits, type EngineKey, type Result } from "./api";

export type Phase = "idle" | "searching" | "reading" | "answering" | "done";

export interface RunState {
  phase: Phase;
  query: string;
  engine: EngineKey;
  results: Result[];
  scores: Record<string, Assessment>;
  threshold: number;
  cached: boolean;
  fetchedAt: string | null;
  agentOn: boolean;
  answers: AnswerResponse | null;
  error: string | null;
  credits: Credits | null;
}

const initial: RunState = {
  phase: "idle", query: "", engine: "google-in", results: [], scores: {}, threshold: 1,
  cached: false, fetchedAt: null, agentOn: false, answers: null, error: null, credits: null,
};

/** Drives one search: start (SerpApi) -> step until every page is scored -> answer. */
export function useSearchRun() {
  const [state, setState] = useState<RunState>(initial);
  const runId = useRef(0);

  const run = useCallback(async (query: string, engine: EngineKey) => {
    const id = ++runId.current; // a newer run cancels this one's updates
    const live = () => id === runId.current;
    setState((s) => ({ ...initial, credits: s.credits, phase: "searching", query, engine }));
    try {
      const started = await api.start(query, engine);
      if (!live()) return;
      setState((s) => ({
        ...s, phase: "reading", results: started.results, threshold: started.threshold,
        cached: started.cached, fetchedAt: started.fetched_at, agentOn: started.agent, credits: started,
      }));
      if (!started.results.length) throw new ApiError("The engine returned no organic results for this question.", 200);
      for (;;) {
        const step = await api.step(started.job);
        if (!live()) return;
        if (step.link && step.slopwatch) {
          const { link, slopwatch } = step;
          setState((s) => ({ ...s, scores: { ...s.scores, [link]: slopwatch } }));
        }
        if (step.done) break;
      }
      if (!started.agent) { setState((s) => ({ ...s, phase: "done" })); return; }
      setState((s) => ({ ...s, phase: "answering" }));
      const answers = await api.answer(started.job);
      if (!live()) return;
      setState((s) => ({ ...s, phase: "done", answers }));
    } catch (e) {
      if (!live()) return;
      const err = e as ApiError;
      const body = err.body as Partial<Credits> | undefined;
      setState((s) => ({
        ...s, error: err.message || "Something went wrong.",
        credits: body && body.session_cap != null ? (body as Credits) : s.credits,
      }));
    }
  }, []);

  return { state, run };
}
