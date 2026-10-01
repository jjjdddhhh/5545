// EditRequestPanel.tsx : 결과 작업공간 아래쪽의 "수정 요청" 영역(설계서 5절 마지막 문단, 13절).
// 1) 사용자가 자연어로 수정을 요청하면 POST /api/projects/{id}/edit-requests로 보내고,
// 2) 에이전트가 부르는 도구를 SSE로 받아 차례로 보여 주고(무엇을 조회하고 무엇을 제안했는지),
// 3) 끝나면 변경 제안을 바뀌기 전과 후로 나란히 보여 주고 제안마다 승인이나 거절을 받는다.
// 에이전트에는 쓰기 도구가 없으므로, 사용자가 승인하기 전에는 결과가 바뀌지 않는다(결정 8).
// 승인하면 서버가 필드를 바꾸고 revision을 남기며, 내레이션이면 자막을 다시 나누고 검수를 다시 한다.
// 그래서 승인 뒤에는 구성안, 매뉴얼, 검수 쿼리만 무효화해 화면을 새로 그린다(설계서 5절 "바뀐 쿼리만 무효화").
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acceptProposal,
  createEditRequest,
  getProposals,
  listEditRequests,
  qk,
  rejectProposal,
} from "../../api/endpoints";
import type { EditStatus, ProposalOut } from "../../api/types";
import { useEditEvents } from "../../hooks/useEditEvents";
import { Badge, btn, ErrorBox, Notice, Spinner } from "../ui";

/** 요청 상태의 한국어 이름과 배지 색. */
const STATUS_VIEW: Record<EditStatus, { label: string; tone: "indigo" | "green" | "amber" | "red" | "slate" }> = {
  running: { label: "처리 중", tone: "indigo" },
  proposed: { label: "제안 있음", tone: "green" },
  refused: { label: "제안 없이 끝남", tone: "slate" },
  limit: { label: "도구 호출 한도 도달", tone: "amber" },
  failed: { label: "실패", tone: "red" },
  done: { label: "처리 완료", tone: "slate" },
};

/** 도구 호출 상태의 표시. blocked는 가드레일이 막은 호출(없는 도구, 빠진 인자, 제안 5개 초과)이다. */
const ACTION_VIEW: Record<string, { label: string; cls: string }> = {
  ok: { label: "완료", cls: "text-emerald-700" },
  error: { label: "오류", cls: "text-red-700" },
  blocked: { label: "차단", cls: "text-orange-700" },
};

// 요청 예시. 설계서 13절 평가 표의 유형(쉬운 표현, 길이 줄이기, 키워드 넣기, 매뉴얼 단계)에서 하나씩 골랐다.
const EXAMPLES = [
  "3번 장면을 초보자용으로 더 쉽게 바꿔 줘",
  "2번 장면 내레이션을 25초 안으로 줄여 줘",
  "보호장갑 언급을 알맞은 장면에 넣어 줘",
  "매뉴얼 2단계 팁을 더 구체적으로 써 줘",
];

/** 도구 인자를 한 줄로 짧게 보여 준다. 긴 값(new_value 등)은 40자에서 자른다. */
function argsText(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args as Record<string, unknown>)
    .map(([k, v]) => {
      const s = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}=${s.length > 40 ? `${s.slice(0, 40)}…` : s}`;
    })
    .join(", ");
}

/**
 * projectId: 수정 요청을 보낼 프로젝트.
 * runId: 현재 결과의 실행 번호. 승인 뒤 검수 결과(qk.checks)를 무효화할 때 쓴다.
 * onShowTarget: 제안의 대상 장면으로 이동할 때 부른다(스토리보드 탭에서 그 장면을 연다). 매뉴얼 제안이면 sceneId가 null이다.
 */
export default function EditRequestPanel({
  projectId,
  runId,
  onShowTarget,
}: {
  projectId: number;
  runId: number | null;
  onShowTarget?: (target: { sceneId: number | null; manual: boolean }) => void;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  // 지금 보고 있는 요청. 새로 보내면 그 요청으로, 처음 열면 가장 최근 요청으로 맞춘다.
  const [currentId, setCurrentId] = useState<number | null>(null);

  // 이력(최근 20개). 처음 열었을 때 마지막 요청을 이어서 보여 주려고 읽는다.
  const history = useQuery({
    queryKey: qk.editRequests(projectId),
    queryFn: () => listEditRequests(projectId),
    enabled: projectId > 0,
  });
  useEffect(() => {
    if (currentId === null && history.data && history.data.length > 0) setCurrentId(history.data[0].id);
  }, [history.data, currentId]);

  const proposals = useQuery({
    queryKey: qk.proposals(currentId ?? 0),
    queryFn: () => getProposals(currentId as number),
    enabled: currentId !== null,
  });

  // 에이전트 진행. 끝나면(done) 제안 목록과 이력을 다시 불러온다.
  const events = useEditEvents(currentId, () => {
    if (currentId !== null) queryClient.invalidateQueries({ queryKey: qk.proposals(currentId) });
    queryClient.invalidateQueries({ queryKey: qk.editRequests(projectId) });
  });
  const running = events.status === "running";

  const send = useMutation({
    mutationFn: () => createEditRequest(projectId, text.trim()),
    onSuccess: (res) => {
      setCurrentId(res.edit_request_id);
      setText("");
      queryClient.invalidateQueries({ queryKey: qk.editRequests(projectId) });
    },
  });

  /** 제안 하나를 처리한 뒤 다시 불러올 쿼리. 승인은 결과를 바꾸므로 구성안, 매뉴얼, 검수도 무효화한다. */
  function refreshAfterDecision(accepted: boolean) {
    if (currentId !== null) queryClient.invalidateQueries({ queryKey: qk.proposals(currentId) });
    queryClient.invalidateQueries({ queryKey: qk.editRequests(projectId) });
    if (accepted) {
      queryClient.invalidateQueries({ queryKey: qk.outline(projectId) });
      queryClient.invalidateQueries({ queryKey: qk.manual(projectId) });
      if (runId) queryClient.invalidateQueries({ queryKey: qk.checks(runId) });
    }
  }

  const canSend = text.trim().length > 0 && text.length <= 1000 && !send.isPending && !running;
  const status = events.status ?? history.data?.find((h) => h.id === currentId)?.status ?? null;

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-800">수정 요청</h2>
        {history.data && history.data.length > 0 && (
          // 예전 요청을 다시 열어 남은 제안을 처리할 수 있게 한다.
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            이전 요청
            <select
              className="rounded border border-slate-300 bg-white px-1.5 py-1 text-xs"
              value={currentId ?? ""}
              onChange={(e) => setCurrentId(Number(e.target.value))}
            >
              {history.data.map((h) => (
                <option key={h.id} value={h.id}>
                  #{h.id} {h.request_text.slice(0, 30)} ({STATUS_VIEW[h.status]?.label ?? h.status})
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      <div className="space-y-4 p-4">
        {/* ---------- 입력 ---------- */}
        <div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Ctrl+Enter(맥은 Cmd+Enter)로 보낸다. Enter만 누르면 줄바꿈이다.
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && canSend) send.mutate();
            }}
            maxLength={1000}
            className="h-20 w-full resize-y rounded-md border border-slate-300 p-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            placeholder="예: 3번 장면을 초보자용으로 더 쉽게 바꿔 줘 (Ctrl+Enter로 보내기)"
            aria-label="수정 요청 입력"
            disabled={running}
          />
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <button type="button" className={btn("primary")} disabled={!canSend} onClick={() => send.mutate()}>
              {send.isPending || running ? <Spinner className="h-3.5 w-3.5" /> : null}
              {running ? "에이전트가 처리하는 중" : "요청 보내기"}
            </button>
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className={btn("ghost", "sm")} onClick={() => setText(ex)} disabled={running}>
                {ex}
              </button>
            ))}
            <span className="ml-auto text-xs text-slate-400">{text.length}/1000자</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            에이전트는 조회와 제안만 하고 직접 바꾸지 않습니다. 승인한 제안만 결과에 반영됩니다. 도구 호출은 요청당 최대 8회, 제안은 최대 5개입니다.
          </p>
          <ErrorBox error={send.error} className="mt-2" />
        </div>

        {/* ---------- 진행 ---------- */}
        {currentId !== null && (
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-slate-700">요청 #{currentId}</span>
              {status && <Badge tone={STATUS_VIEW[status]?.tone ?? "slate"}>{STATUS_VIEW[status]?.label ?? status}</Badge>}
              {events.requestText && <span className="text-slate-600">“{events.requestText}”</span>}
              {events.conn === "error" && <span className="text-xs text-red-600">진행 알림 연결이 끊겼습니다.</span>}
            </div>
            {events.actions.length === 0 ? (
              <p className="text-xs text-slate-500">
                {running ? "에이전트가 무엇을 할지 고르는 중입니다." : "부른 도구가 없습니다."}
              </p>
            ) : (
              <ol className="space-y-1 text-xs">
                {events.actions.map((a) => (
                  <li key={a.seq} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="w-5 text-right text-slate-400">{a.seq}.</span>
                    <span className="font-medium text-slate-800">{a.label || a.tool_name}</span>
                    <code className="text-slate-500">{a.tool_name}</code>
                    <span className={ACTION_VIEW[a.status]?.cls ?? ""}>{ACTION_VIEW[a.status]?.label ?? a.status}</span>
                    {a.latency_ms !== null && <span className="text-slate-400">{a.latency_ms}ms</span>}
                    <span className="basis-full pl-7 text-slate-500">{argsText(a.arguments)}</span>
                    {a.status !== "ok" && a.result_summary && (
                      <span className="basis-full pl-7 text-red-600">{a.result_summary}</span>
                    )}
                  </li>
                ))}
                {running && (
                  <li className="flex items-center gap-2 pl-7 text-slate-500">
                    <Spinner className="h-3 w-3" /> 다음 행동을 고르는 중입니다.
                  </li>
                )}
              </ol>
            )}
            {events.summary && !running && (
              <p className="mt-2 whitespace-pre-wrap border-t border-slate-200 pt-2 text-sm text-slate-700">{events.summary}</p>
            )}
          </div>
        )}

        {/* ---------- 제안 ---------- */}
        {currentId !== null && !running && (
          <div className="space-y-3">
            <ErrorBox error={proposals.error} />
            {proposals.data && proposals.data.length === 0 && status !== "running" && (
              <Notice>이 요청에서 만든 변경 제안이 없습니다.</Notice>
            )}
            {proposals.data?.map((p) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                onDecided={refreshAfterDecision}
                onShow={() => onShowTarget?.({ sceneId: p.scene_id, manual: p.target_type === "manual_step" })}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/**
 * 제안 하나. 대상과 필드, 이유, 경고(사용자가 고친 필드, 내용이 바뀐 제안), 제안 검수 결과,
 * 바뀌기 전과 후(나란히), 내레이션이면 자막 미리보기, 승인·거절 버튼을 보여 준다.
 */
function ProposalCard({
  proposal: p,
  onDecided,
  onShow,
}: {
  proposal: ProposalOut;
  onDecided: (accepted: boolean) => void;
  onShow: () => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const accept = useMutation({ mutationFn: () => acceptProposal(p.id), onSuccess: () => onDecided(true) });
  const reject = useMutation({
    mutationFn: () => rejectProposal(p.id, reason.trim()),
    onSuccess: () => {
      setRejecting(false);
      onDecided(false);
    },
  });
  const pending = p.status === "pending";
  const checkResults = p.checks?.results ?? [];
  const checkOk = p.checks?.ok;

  return (
    <article
      className={`rounded-md border p-3 ${
        p.status === "accepted" ? "border-emerald-200 bg-emerald-50/40" : p.status === "rejected" ? "border-slate-200 bg-slate-50 opacity-70" : "border-slate-300 bg-white"
      }`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button type="button" className="text-sm font-semibold text-indigo-700 hover:underline" onClick={onShow} title="이 대상으로 이동">
          {p.target_label || p.target_type}
        </button>
        <Badge tone="indigo">{p.field_label}</Badge>
        {p.status === "accepted" && <Badge tone="green">승인함</Badge>}
        {p.status === "rejected" && <Badge>거절함</Badge>}
        {pending && checkOk === true && <Badge tone="green">제안 검수 통과</Badge>}
        {pending && checkOk === false && <Badge tone="red">제안 검수 실패</Badge>}
      </div>

      {/* 사람이 고친 필드를 모르고 덮어쓰지 않게 경고한다(설계서 13절 가드레일). */}
      {p.user_edited && pending && (
        <div className="mb-2">
          <Notice tone="warn">사용자가 직접 고친 필드입니다. 승인하면 직접 고친 내용을 이 제안으로 바꿉니다.</Notice>
        </div>
      )}
      {p.stale && (
        <div className="mb-2">
          <Notice tone="warn">제안을 만든 뒤 내용이 바뀌어 승인할 수 없습니다. 지금 내용으로 다시 요청해 주세요.</Notice>
        </div>
      )}
      {p.reason && <p className="mb-2 text-xs text-slate-600">이유: {p.reason}</p>}

      <div className="grid gap-2 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">바뀌기 전</div>
          <div className="min-h-12 whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-2 text-sm text-slate-700">
            {p.before_value || <span className="text-slate-400">(비어 있음)</span>}
          </div>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium text-slate-500">바뀐 후</div>
          <div className="min-h-12 whitespace-pre-wrap rounded border border-indigo-200 bg-indigo-50/50 p-2 text-sm text-slate-900">
            {p.after_value}
          </div>
        </div>
      </div>

      {/* 내레이션 제안은 코드가 나눈 자막 미리보기를 붙인다(LLM이 아니라 subtitles.py가 나눈다). */}
      {p.subtitle_preview.length > 0 && (
        <div className="mt-2">
          <div className="mb-1 text-xs font-medium text-slate-500">자막 미리보기(코드가 나눔)</div>
          <div className="flex flex-wrap gap-1.5">
            {p.subtitle_preview.map((c, i) => (
              <span key={i} className="whitespace-pre rounded bg-slate-800 px-2 py-1 text-xs leading-snug text-white">
                {c}
              </span>
            ))}
          </div>
        </div>
      )}

      {pending && checkResults.length > 0 && checkResults[0].code !== "ALL" && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {checkResults.map((r, i) => (
            <li key={i} className={r.result === "fail" ? "text-red-700" : "text-orange-700"}>
              {r.code} {r.message}
            </li>
          ))}
        </ul>
      )}

      {pending && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" className={btn("primary", "sm")} disabled={p.stale || accept.isPending} onClick={() => accept.mutate()}>
            {accept.isPending && <Spinner className="h-3 w-3" />}승인
          </button>
          {!rejecting ? (
            <button type="button" className={btn("secondary", "sm")} onClick={() => setRejecting(true)}>
              거절
            </button>
          ) : (
            <>
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={300}
                placeholder="거절 사유(선택)"
                className="w-56 rounded border border-slate-300 px-2 py-1 text-xs"
                aria-label="거절 사유"
              />
              <button type="button" className={btn("danger", "sm")} disabled={reject.isPending} onClick={() => reject.mutate()}>
                거절 확정
              </button>
              <button type="button" className={btn("ghost", "sm")} onClick={() => setRejecting(false)}>
                취소
              </button>
            </>
          )}
        </div>
      )}
      <ErrorBox error={accept.error || reject.error} className="mt-2" />
    </article>
  );
}
