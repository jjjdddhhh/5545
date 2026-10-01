// RunPage.tsx : 4번 화면 "생성 진행"(설계서 5절).
// 단계별 진행 상태를 실시간으로 보여 주고, 실패한 단계와 사유를 표시하며, 끝나면 결과 작업공간으로 이동한다.
// 진행 상태는 hooks/useRunEvents가 SSE로 받아 모은다. 이 파일은 그 상태를 그리기만 한다.
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { qk } from "../api/endpoints";
import { Badge, Card, ErrorBox, Notice, Spinner, btn } from "../components/ui";
import { useIdParam } from "../hooks/useIdParam";
import { useRunEvents, type LlmLogLine, type StageView } from "../hooks/useRunEvents";
import { RUN_STATUS_LABEL, STAGE_LABEL, STAGE_STATUS_LABEL } from "../lib/labels";

// 완료 뒤 결과 화면으로 자동 이동하기까지 기다리는 시간(초). 완료 표시를 잠깐 보여 주고 넘어가려고 3초로 정했다.
const AUTO_NAV_SEC = 3;

/** 단계 상태 표시 아이콘. 진행 중이면 회전, 완료는 체크, 실패는 X, 대기는 빈 원이다. */
function StageIcon({ status }: { status: StageView["status"] }) {
  if (status === "running") return <Spinner className="h-4 w-4 text-indigo-600" />;
  if (status === "done")
    return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-[10px] text-white">✓</span>;
  if (status === "failed")
    return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] text-white">✕</span>;
  return <span className="h-4 w-4 rounded-full border-2 border-slate-300" />;
}

/** LLM 호출 한 줄. 단계, 시도 횟수, 상태, 토큰 수, 걸린 시간, 잘림 위험 경고를 보여 준다. */
function LogLine({ line }: { line: LlmLogLine }) {
  const tone = line.status === "ok" ? "text-emerald-700" : line.status === "retry" ? "text-amber-700" : "text-red-700";
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-b border-slate-100 py-1 font-mono text-xs">
      <span className="text-slate-400">{line.at.toLocaleTimeString("ko-KR")}</span>
      <span className="font-semibold text-slate-700">{STAGE_LABEL[line.stage] ?? line.stage}</span>
      <span>{line.attempt ?? 1}번째 시도</span>
      <span className={tone}>{line.status ?? "알 수 없음"}</span>
      <span className="text-slate-500">
        입력 {line.tokens_in ?? "-"} / 출력 {line.tokens_out ?? "-"} 토큰
      </span>
      <span className="text-slate-500">{line.latency_ms ?? "-"}ms</span>
      {line.truncation_risk && (
        <span className="rounded bg-amber-100 px-1 text-amber-800">출력이 잘렸을 수 있습니다(토큰 한도 근접)</span>
      )}
    </li>
  );
}

export default function RunPage() {
  const runId = useIdParam("runId");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const run = useRunEvents(runId);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [autoNav, setAutoNav] = useState(true);
  const logRef = useRef<HTMLUListElement>(null);

  const workspaceUrl = run.projectId ? `/projects/${run.projectId}/workspace` : null;

  // 실행이 끝나면 결과가 바뀌었으므로 그 프로젝트의 결과 쿼리를 무효화한다.
  // 무효화하지 않으면 작업공간이 이전 실행의 구성안을 캐시에서 보여 줄 수 있다.
  useEffect(() => {
    if ((run.status === "done" || run.status === "failed") && run.projectId) {
      const pid = run.projectId;
      queryClient.invalidateQueries({ queryKey: qk.project(pid) });
      queryClient.invalidateQueries({ queryKey: qk.outline(pid) });
      queryClient.invalidateQueries({ queryKey: qk.manual(pid) });
      queryClient.invalidateQueries({ queryKey: qk.projectsAll });
    }
  }, [run.status, run.projectId, queryClient]);

  // 성공으로 끝나면 몇 초 세다가 결과 작업공간으로 넘어간다. 사용자가 "머무르기"를 누르면 멈춘다.
  useEffect(() => {
    if (run.status !== "done" || !workspaceUrl || !autoNav) {
      setCountdown(null);
      return;
    }
    setCountdown(AUTO_NAV_SEC);
    const t = setInterval(() => {
      setCountdown((c) => {
        if (c === null) return c;
        if (c <= 1) {
          clearInterval(t);
          navigate(workspaceUrl);
          return 0;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [run.status, workspaceUrl, autoNav, navigate]);

  // 새 LLM 호출 기록이 오면 목록을 맨 아래로 내린다.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [run.logs.length]);

  if (runId === null) return <ErrorBox error="잘못된 주소입니다. 실행 번호를 확인해 주세요." />;

  const doneCount = run.stages.filter((s) => s.status === "done").length;
  const percent = run.stages.length ? Math.round((doneCount / run.stages.length) * 100) : 0;

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">
          생성 진행 <span className="text-sm font-normal text-slate-500">실행 {runId}</span>
        </h1>
        <div className="flex items-center gap-2 text-sm">
          {run.llmModel && <Badge>모델 {run.llmModel}</Badge>}
          <Badge tone={run.status === "done" ? "green" : run.status === "failed" ? "red" : "indigo"}>
            {run.status ? RUN_STATUS_LABEL[run.status] : "연결 중"}
          </Badge>
          {run.projectId && (
            <Link to={`/projects/${run.projectId}/settings`} className="text-slate-500 underline">
              조건 설정으로
            </Link>
          )}
        </div>
      </div>

      {run.conn === "error" && (
        <ErrorBox error="진행 알림에 연결하지 못했습니다. 실행 번호가 맞는지, 백엔드 서버가 켜져 있는지 확인해 주세요." />
      )}
      {run.conn === "connecting" && run.status && (
        <Notice tone="warn">연결이 잠시 끊겨 다시 연결하는 중입니다. 다시 연결되면 현재 상태를 서버에서 다시 받아옵니다.</Notice>
      )}

      {/* 전체 진행 막대. 끝난 단계 수 / 전체 단계 수로 계산한다. */}
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className={`h-full transition-all ${run.status === "failed" ? "bg-red-500" : "bg-indigo-600"}`}
          style={{ width: `${percent}%` }}
        />
      </div>

      <Card title="단계별 진행">
        {run.stages.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Spinner /> 서버에서 진행 상태를 받는 중입니다.
          </div>
        ) : (
          <ol className="space-y-2">
            {run.stages.map((s, i) => {
              const prog = run.progress[s.key];
              return (
                <li key={s.key} className="flex items-start gap-3 rounded-md px-2 py-1.5 hover:bg-slate-50">
                  <div className="pt-0.5">
                    <StageIcon status={s.status} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">
                        {i + 1}. {s.label}
                      </span>
                      <span
                        className={`text-xs ${
                          s.status === "failed" ? "text-red-600" : s.status === "running" ? "text-indigo-600" : "text-slate-500"
                        }`}
                      >
                        {STAGE_STATUS_LABEL[s.status]}
                      </span>
                      {s.latencyMs !== null && <span className="text-xs text-slate-400">{(s.latencyMs / 1000).toFixed(1)}초</span>}
                      {s.stats && s.stats.tokens_out > 0 && (
                        <span className="text-xs text-slate-400">
                          LLM 호출 {s.stats.calls}회 · 출력 {s.stats.tokens_out} 토큰
                          {s.stats.retry > 0 && ` · 재요청 ${s.stats.retry}회`}
                          {s.stats.failed > 0 && ` · 실패 ${s.stats.failed}회`}
                        </span>
                      )}
                    </div>
                    {/* 장면 상세와 내레이션 단계는 장면마다 따로 LLM을 부르므로 몇 번째 장면인지 보여 준다. */}
                    {prog && (s.status === "running" || s.status === "failed") && (
                      <div className="mt-1">
                        <div className="text-xs text-slate-600">
                          장면 {prog.current}/{prog.total} · {prog.title}
                        </div>
                        <div className="mt-1 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-slate-200">
                          <div
                            className="h-full bg-indigo-400"
                            style={{ width: `${Math.round(((prog.current - 1) / Math.max(1, prog.total)) * 100)}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </Card>

      {run.status === "failed" && (
        <Card title="실패 사유">
          <p className="whitespace-pre-wrap text-sm text-red-700">{run.errorMessage ?? "원인을 알 수 없는 오류로 실패했습니다."}</p>
          <div className="mt-3 flex gap-2">
            {run.projectId && (
              <Link to={`/projects/${run.projectId}/settings`} className={btn("primary")}>
                조건을 확인하고 다시 생성
              </Link>
            )}
            {workspaceUrl && (
              <Link to={workspaceUrl} className={btn("secondary")}>
                이전 결과 보기
              </Link>
            )}
          </div>
        </Card>
      )}

      {run.status === "done" && workspaceUrl && (
        <Notice tone="success">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              생성을 마쳤습니다.
              {run.checks && run.checks.pass_rate !== null && ` 자동 검수 통과율은 ${Math.round(run.checks.pass_rate * 100)}%입니다.`}
              {countdown !== null && ` ${countdown}초 뒤 결과 작업공간으로 이동합니다.`}
            </span>
            <span className="flex gap-2">
              {countdown !== null && (
                <button type="button" className={btn("secondary", "sm")} onClick={() => setAutoNav(false)}>
                  이 화면에 머무르기
                </button>
              )}
              <Link to={workspaceUrl} className={btn("primary", "sm")}>
                결과 작업공간으로
              </Link>
            </span>
          </div>
        </Notice>
      )}

      <Card title={`LLM 호출 기록 (${run.logs.length})`}>
        {run.logs.length === 0 ? (
          <p className="text-sm text-slate-500">
            이 화면을 연 뒤의 LLM 호출이 여기에 나타납니다. 이미 끝난 실행이면 단계별 합계만 위에 표시됩니다.
          </p>
        ) : (
          <ul ref={logRef} className="max-h-72 overflow-auto">
            {run.logs.map((l) => (
              <LogLine key={l.seq} line={l} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
