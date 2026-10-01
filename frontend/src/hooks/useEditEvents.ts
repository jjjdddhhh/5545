// useEditEvents.ts : 수정 요청 에이전트의 진행을 SSE로 받아 상태로 모으는 훅(설계서 13절).
// 서버(GET /api/edit-requests/{id}/events)는 연결하자마자 DB에 저장된 지금까지의 상태(snapshot)를 보내고,
// 그다음 에이전트가 도구를 하나 부를 때마다 tool 이벤트를, 끝나면 done 이벤트를 보낸다.
// snapshot을 기준 상태로 삼으므로, 연결이 끊겼다 다시 이어져도(브라우저가 자동으로 다시 연결한다) 화면이 바로잡힌다.
import { useEffect, useReducer } from "react";
import { API_BASE } from "../api/client";
import type { AgentActionOut, EditDoneEvent, EditSnapshotEvent, EditStatus, EditToolEvent } from "../api/types";

export interface EditEventsState {
  status: EditStatus | null;      // 아직 snapshot을 받기 전이면 null
  requestText: string;
  summary: string | null;
  actions: AgentActionOut[];      // 도구 호출 목록(seq 순서)
  conn: "connecting" | "open" | "closed" | "error";
}

const INITIAL: EditEventsState = { status: null, requestText: "", summary: null, actions: [], conn: "connecting" };

type Action =
  | { kind: "reset" }
  | { kind: "conn"; conn: EditEventsState["conn"] }
  | { kind: "event"; type: string; data: unknown };

/** 같은 seq의 도구 호출이 snapshot과 tool 이벤트로 두 번 올 수 있으므로 seq로 합친 뒤 정렬한다. */
function mergeAction(list: AgentActionOut[], a: AgentActionOut): AgentActionOut[] {
  const rest = list.filter((x) => x.seq !== a.seq);
  return [...rest, a].sort((x, y) => x.seq - y.seq);
}

function reducer(state: EditEventsState, action: Action): EditEventsState {
  switch (action.kind) {
    case "reset":
      return INITIAL;
    case "conn":
      return { ...state, conn: action.conn };
    case "event":
      if (action.type === "snapshot") {
        // snapshot은 DB의 상태 전체다. 이미 받은 tool 이벤트가 더 최신일 수 있으므로 목록은 합친다.
        const ev = action.data as EditSnapshotEvent;
        let actions = state.actions;
        for (const a of ev.actions) actions = mergeAction(actions, a);
        return { ...state, status: ev.status, requestText: ev.request_text, summary: ev.summary, actions };
      }
      if (action.type === "tool") {
        const ev = action.data as EditToolEvent;
        return { ...state, actions: mergeAction(state.actions, ev) };
      }
      if (action.type === "done") {
        const ev = action.data as EditDoneEvent;
        return { ...state, status: ev.status, summary: ev.summary };
      }
      return state;
    default:
      return state;
  }
}

const EVENT_TYPES = ["snapshot", "start", "tool", "done"];

/**
 * editRequestId: 지켜볼 수정 요청 번호. null이면 연결하지 않는다.
 * onDone: done 이벤트를 받았을 때 한 번 부른다(제안 목록을 다시 불러오는 데 쓴다).
 * 끝난 요청이면 서버가 snapshot과 done만 보내고 닫으므로, 이력에서 예전 요청을 열어도 같은 훅을 쓴다.
 */
export function useEditEvents(editRequestId: number | null, onDone?: (status: EditStatus) => void): EditEventsState {
  const [state, dispatch] = useReducer(reducer, INITIAL);

  useEffect(() => {
    if (editRequestId === null) return;
    dispatch({ kind: "reset" });
    const es = new EventSource(`${API_BASE}/api/edit-requests/${editRequestId}/events`);
    let finished = false;

    const handlers = EVENT_TYPES.map((type) => {
      const fn = (e: MessageEvent) => {
        let data: unknown;
        try {
          data = JSON.parse(e.data);
        } catch {
          return; // ping처럼 JSON이 아닌 줄은 무시한다
        }
        dispatch({ kind: "event", type, data });
        if (type === "done") {
          finished = true;
          es.close();     // 닫지 않으면 브라우저가 끝난 요청에 계속 다시 연결한다
          dispatch({ kind: "conn", conn: "closed" });
          onDone?.((data as EditDoneEvent).status);
        }
      };
      es.addEventListener(type, fn as EventListener);
      return [type, fn] as const;
    });
    es.onopen = () => dispatch({ kind: "conn", conn: "open" });
    es.onerror = () => {
      if (finished) return;
      dispatch({ kind: "conn", conn: es.readyState === EventSource.CLOSED ? "error" : "connecting" });
    };
    return () => {
      handlers.forEach(([type, fn]) => es.removeEventListener(type, fn as EventListener));
      es.close();
    };
    // onDone은 부를 때마다 새 함수일 수 있어 의존성에서 뺀다. 연결은 요청 번호가 바뀔 때만 새로 맺는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editRequestId]);

  return state;
}
