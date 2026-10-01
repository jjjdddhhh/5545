// useRunEvents.ts : 생성 실행의 진행 알림(SSE)을 받아 화면 상태로 모으는 훅.
// 설계서 5절 "브라우저 기본 EventSource로 SSE를 받아 단계별 진행 표시를 갱신한다"를 구현한다.
//
// 서버(backend/app/api/runs.py)의 약속:
// - 연결하면 언제나 snapshot(DB로 다시 만든 단계별 상태)을 먼저 보낸다.
// - 이미 끝난 실행이면 snapshot 다음에 done을 보내고 연결을 닫는다.
// - 진행 중이면 run_start, stage_start, progress, llm_call, stage_done, checks, stage_error, done이 차례로 온다.
// EventSource는 연결이 끊기면 스스로 다시 연결하고, 서버는 다시 연결될 때마다 snapshot을 새로 보낸다.
// 그래서 snapshot을 "믿을 수 있는 기준 상태"로 보고 단계 목록과 상태를 통째로 바꾸며, 나머지 이벤트는 그 위에 덧칠한다.
import { useEffect, useReducer } from "react";
import { API_BASE } from "../api/client";
import type {
  CheckSummary,
  ChecksEvent,
  DoneEvent,
  LlmCallEvent,
  ProgressEvent,
  RunStartEvent,
  RunStatus,
  SnapshotEvent,
  StageDoneEvent,
  StageErrorEvent,
  StageStartEvent,
  StageStats,
  StageStatus,
} from "../api/types";
import { STAGE_LABEL } from "../lib/labels";

/** 화면에 그릴 단계 하나. latencyMs는 stage_done에서 채우고, 놓쳤으면 snapshot의 latency_ms로 채운다. stats는 snapshot에서 채운다. */
export interface StageView {
  key: string;
  label: string;
  status: StageStatus;
  stats: StageStats | null;
  latencyMs: number | null;
}

/** 장면별 진행(장면 상세, 내레이션 단계). "3/5 · 작업 전 점검"처럼 보여 준다. */
export interface ProgressView {
  current: number;
  total: number;
  title: string;
}

/** LLM 호출 기록 한 줄. 화면 목록의 key로 쓰려고 일련번호(seq)를 붙인다. */
export interface LlmLogLine extends LlmCallEvent {
  seq: number;
  at: Date;
}

/** 연결 상태. connecting은 연결 중, open은 받는 중, closed는 끝나서 닫음, error는 연결할 수 없음이다. */
export type ConnState = "connecting" | "open" | "closed" | "error";

export interface RunEventsState {
  projectId: number | null;
  status: RunStatus | null;
  stages: StageView[];
  progress: Record<string, ProgressView>;
  logs: LlmLogLine[];
  checks: CheckSummary | null;
  errorMessage: string | null;
  llmModel: string | null;
  conn: ConnState;
}

const INITIAL: RunEventsState = {
  projectId: null,
  status: null,
  stages: [],
  progress: {},
  logs: [],
  checks: null,
  errorMessage: null,
  llmModel: null,
  conn: "connecting",
};

// LLM 호출 기록은 최근 300줄만 둔다. 장면 40개에 재요청까지 해도 100여 줄이므로 넉넉하고,
// 혹시 이벤트가 아주 많이 와도 화면이 느려지지 않게 상한을 둔다.
const MAX_LOGS = 300;

type Action =
  | { kind: "event"; type: string; data: unknown }
  | { kind: "conn"; conn: ConnState }
  | { kind: "reset" };

/** 단계 하나의 상태만 바꾼 새 목록을 돌려준다. 목록에 없는 단계면 맨 뒤에 더한다. */
function patchStage(stages: StageView[], key: string, patch: Partial<StageView>, label?: string): StageView[] {
  if (!stages.some((s) => s.key === key)) {
    return [
      ...stages,
      { key, label: label ?? STAGE_LABEL[key] ?? key, status: "pending", stats: null, latencyMs: null, ...patch },
    ];
  }
  return stages.map((s) => (s.key === key ? { ...s, ...patch } : s));
}

/** 이벤트 하나를 받아 상태를 바꾸는 리듀서. 이벤트 종류마다 무엇을 바꾸는지 아래에 적었다. */
function reducer(state: RunEventsState, action: Action): RunEventsState {
  if (action.kind === "reset") return INITIAL;
  if (action.kind === "conn") return { ...state, conn: action.conn };

  switch (action.type) {
    case "snapshot": {
      // 기준 상태. 단계 목록과 상태를 통째로 바꾼다.
      // 걸린 시간은 실시간 stage_done에서 받은 값이 있으면 그것을, 없으면(화면이 늦게 연결되어 놓친 경우) snapshot의 값을 쓴다.
      const ev = action.data as SnapshotEvent;
      const prev = new Map(state.stages.map((s) => [s.key, s]));
      return {
        ...state,
        projectId: ev.project_id,
        status: ev.status,
        errorMessage: ev.error_message,
        llmModel: ev.llm_model,
        stages: ev.stages.map((s) => ({
          key: s.key,
          label: s.label,
          status: s.status,
          stats: s.stats,
          latencyMs: prev.get(s.key)?.latencyMs ?? s.latency_ms ?? null,
        })),
      };
    }
    case "run_start": {
      // 실행이 막 시작됨. snapshot이 queued 상태로 단계를 이미 보냈다면 그대로 두고, 없으면 대기 상태로 채운다.
      const ev = action.data as RunStartEvent;
      const stages = state.stages.length
        ? state.stages
        : ev.stages.map((s) => ({ key: s.key, label: s.label, status: "pending" as StageStatus, stats: null, latencyMs: null }));
      return { ...state, status: "running", stages };
    }
    case "stage_start": {
      const ev = action.data as StageStartEvent;
      return { ...state, status: "running", stages: patchStage(state.stages, ev.stage, { status: "running" }, ev.label) };
    }
    case "stage_done": {
      const ev = action.data as StageDoneEvent;
      return {
        ...state,
        stages: patchStage(state.stages, ev.stage, { status: "done", latencyMs: ev.latency_ms }, ev.label),
      };
    }
    case "progress": {
      const ev = action.data as ProgressEvent;
      return { ...state, progress: { ...state.progress, [ev.stage]: { current: ev.current, total: ev.total, title: ev.title } } };
    }
    case "llm_call": {
      const ev = action.data as LlmCallEvent;
      const line: LlmLogLine = { ...ev, seq: (state.logs[state.logs.length - 1]?.seq ?? 0) + 1, at: new Date() };
      return { ...state, logs: [...state.logs, line].slice(-MAX_LOGS) };
    }
    case "checks": {
      const ev = action.data as ChecksEvent;
      return { ...state, checks: ev.summary };
    }
    case "stage_error": {
      const ev = action.data as StageErrorEvent;
      const stages = ev.stage ? patchStage(state.stages, ev.stage, { status: "failed" }, ev.label ?? undefined) : state.stages;
      return { ...state, stages, errorMessage: ev.message };
    }
    case "done": {
      // 실패로 끝났으면 메시지를 남긴다. 성공이면 남은 단계를 모두 완료로 표시한다(이벤트를 놓쳤을 때를 대비).
      const ev = action.data as DoneEvent;
      const stages =
        ev.status === "done" ? state.stages.map((s) => ({ ...s, status: "done" as StageStatus })) : state.stages;
      return {
        ...state,
        status: ev.status,
        stages,
        errorMessage: ev.status === "failed" ? (ev.message ?? state.errorMessage) : state.errorMessage,
      };
    }
    default:
      return state;
  }
}

// 서버가 보내는 이벤트 이름. sse-starlette는 "event:" 줄에 이 이름을 넣으므로 이름마다 따로 듣는다.
const EVENT_TYPES = ["snapshot", "run_start", "stage_start", "stage_done", "progress", "llm_call", "checks", "stage_error", "done"];

/**
 * runId: 지켜볼 실행 번호. null이면 연결하지 않는다.
 * 돌려주는 값: 지금까지 모은 진행 상태(RunEventsState).
 * 화면을 떠나거나(언마운트) done을 받으면 EventSource를 닫는다. 닫지 않으면 브라우저가 끝난 실행에 계속 다시 연결한다.
 */
export function useRunEvents(runId: number | null): RunEventsState {
  const [state, dispatch] = useReducer(reducer, INITIAL);

  useEffect(() => {
    if (runId === null) return;
    dispatch({ kind: "reset" });
    const es = new EventSource(`${API_BASE}/api/runs/${runId}/events`);
    let finished = false;

    const handlers = EVENT_TYPES.map((type) => {
      const fn = (e: MessageEvent) => {
        let data: unknown;
        try {
          data = JSON.parse(e.data);
        } catch {
          return; // JSON이 아닌 줄(ping 등)은 무시한다
        }
        dispatch({ kind: "event", type, data });
        if (type === "done") {
          finished = true;
          es.close();
          dispatch({ kind: "conn", conn: "closed" });
        }
      };
      es.addEventListener(type, fn as EventListener);
      return [type, fn] as const;
    });

    es.onopen = () => dispatch({ kind: "conn", conn: "open" });
    es.onerror = () => {
      if (finished) return;
      // readyState가 CLOSED면 브라우저가 다시 연결을 포기한 것이다(예: 404, 서버가 JSON 오류를 돌려줌).
      // CONNECTING이면 잠깐 끊겨 다시 연결하는 중이므로, 다시 연결되면 snapshot이 상태를 바로잡는다.
      dispatch({ kind: "conn", conn: es.readyState === EventSource.CLOSED ? "error" : "connecting" });
    };

    return () => {
      handlers.forEach(([type, fn]) => es.removeEventListener(type, fn as EventListener));
      es.close();
    };
  }, [runId]);

  return state;
}
