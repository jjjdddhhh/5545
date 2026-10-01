// WorkspacePage.tsx : 5번 화면 "결과 작업공간"(설계서 5절 와이어프레임). 사용자가 가장 오래 머무는 화면이다.
// - 맨 위 줄: 프로젝트 제목, "전체 다시 생성"(조건 설정 화면으로 이동), "같은 조건으로 다시 생성", "내보내기"(강조).
// - 탭 다섯 개: 구성안, 스토리보드, 내레이션·자막, 매뉴얼·일정, 검수.
// - 스토리보드와 내레이션·자막 탭의 본문은 세 칸이다. 왼쪽은 장면 목록, 가운데는 선택한 장면 편집, 오른쪽은 검수 패널이다.
// - 맨 아래에는 수정 요청 에이전트 자리(EditRequestPanel)를 둔다. 단계 7에서 기능을 붙인다.
//
// 데이터는 네 쿼리로 나눠 받는다: 프로젝트 요약(qk.project), 구성안(qk.outline), 매뉴얼(qk.manual, 매뉴얼 탭에서만),
// 검수(qk.checks(runId)). 나눠 두어야 수정 뒤에 바뀐 쿼리만 무효화할 수 있다(설계서 5절).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { isStatus } from "../api/client";
import { getChecks, getOutline, getProject, qk, startRun } from "../api/endpoints";
import CheckPanel from "../components/workspace/CheckPanel";
import ChecksTab from "../components/workspace/ChecksTab";
import EditRequestPanel from "../components/workspace/EditRequestPanel";
import ExportMenu from "../components/workspace/ExportMenu";
import ManualTab from "../components/workspace/ManualTab";
import NarrationTimeline from "../components/workspace/NarrationTimeline";
import OutlineTab from "../components/workspace/OutlineTab";
import SceneEditor from "../components/workspace/SceneEditor";
import SceneList from "../components/workspace/SceneList";
import { Card, ErrorBox, Loading, Notice, RunStatusBadge, Spinner, btn } from "../components/ui";
import { useIdParam } from "../hooks/useIdParam";
import { CONTENT_TYPE_LABEL, formatDateTime } from "../lib/labels";

/** 탭 키와 이름. 순서는 와이어프레임과 같다. */
const TABS = [
  { key: "outline", label: "구성안" },
  { key: "storyboard", label: "스토리보드" },
  { key: "narration", label: "내레이션·자막" },
  { key: "manual", label: "매뉴얼·일정" },
  { key: "checks", label: "검수" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export default function WorkspacePage() {
  const projectId = useIdParam("id");
  const pid = projectId ?? 0;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // 고른 탭과 장면은 주소의 검색어(?tab=...&scene=...)에 둔다. 새로 고침하거나 주소를 공유해도 같은 화면이 열리게 하기 위해서다.
  const [params, setParams] = useSearchParams();

  const project = useQuery({ queryKey: qk.project(pid), queryFn: () => getProject(pid), enabled: pid > 0 });
  // 404는 "구성안 없음"(매뉴얼형으로만 생성했거나 아직 생성 전)이라 오류가 아니다.
  const outline = useQuery({ queryKey: qk.outline(pid), queryFn: () => getOutline(pid), enabled: pid > 0, retry: false });

  // 검수에 쓸 실행 번호. 구성안이 있으면 구성안의 실행, 매뉴얼만 있으면 매뉴얼의 실행이다.
  const runId = outline.data?.outline.run_id ?? project.data?.outline?.run_id ?? project.data?.manual?.run_id ?? null;
  const checks = useQuery({
    queryKey: qk.checks(runId ?? 0),
    queryFn: () => getChecks(runId as number),
    enabled: runId !== null,
  });

  const hasOutline = Boolean(outline.data);
  const defaultTab: TabKey = hasOutline || !project.data?.manual ? "storyboard" : "manual";
  const tabParam = params.get("tab");
  const tab: TabKey = TABS.some((t) => t.key === tabParam) ? (tabParam as TabKey) : defaultTab;

  const sceneParam = Number(params.get("scene"));
  const scenes = outline.data?.scenes ?? [];
  // 주소의 장면이 없거나(삭제·다른 실행) 지정하지 않았으면 첫 장면을 고른다.
  const selected = scenes.find((s) => s.id === sceneParam) ?? scenes[0] ?? null;

  /** 탭이나 장면을 바꾼다. 다른 검색어는 그대로 두고 바꿀 값만 고친다. 뒤로 가기 기록을 쌓지 않게 replace로 바꾼다. */
  function setView(next: { tab?: TabKey; scene?: number }) {
    const p = new URLSearchParams(params);
    if (next.tab) p.set("tab", next.tab);
    if (next.scene) p.set("scene", String(next.scene));
    setParams(p, { replace: true });
  }

  // 구성안이 없는 프로젝트(매뉴얼형)에서 스토리보드 탭이 주소에 남아 있으면 매뉴얼 탭으로 보낸다.
  useEffect(() => {
    if (outline.isFetched && !hasOutline && project.data?.manual && (tab === "storyboard" || tab === "narration")) {
      setView({ tab: "manual" });
    }
    // setView는 매번 새로 만들어지는 함수라 의존성에서 뺐다. 조건이 바뀔 때만 다시 확인하면 충분하다.
  }, [outline.isFetched, hasOutline, project.data?.manual, tab]);

  /** 같은 조건으로 다시 생성. 조건을 바꾸지 않고 바로 실행을 시작해 진행 화면으로 간다. */
  const rerun = useMutation({
    mutationFn: () => startRun(pid),
    onSuccess: ({ run_id }) => {
      queryClient.invalidateQueries({ queryKey: qk.project(pid) });
      navigate(`/runs/${run_id}`);
    },
  });

  // 확인 창을 띄울 때 결과가 새 실행으로 바뀐다는 것을 알려 준다. 이전 실행은 DB에 그대로 남는다.
  const [confirmRerun, setConfirmRerun] = useState(false);

  if (projectId === null) return <ErrorBox error="잘못된 주소입니다. 프로젝트 번호를 확인해 주세요." />;
  if (project.isLoading || outline.isLoading) return <Loading />;
  if (project.isError) return <ErrorBox error={project.error} />;
  if (outline.isError && !isStatus(outline.error, 404)) return <ErrorBox error={outline.error} />;

  const p = project.data!;
  const latest = p.latest_run;
  const running = latest && (latest.status === "running" || latest.status === "queued");

  return (
    <div className="space-y-4">
      {/* ---------- 맨 위 줄: 제목과 주요 단추 ---------- */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold text-slate-900">{p.title}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {p.setting && <span>{CONTENT_TYPE_LABEL[p.setting.content_type]}</span>}
            {p.setting && <span>· 대상 {p.setting.audience}</span>}
            {latest && (
              <>
                <span>· 최근 실행 {latest.id}</span>
                <RunStatusBadge status={latest.status} />
                {latest.finished_at && <span>{formatDateTime(latest.finished_at)}</span>}
              </>
            )}
            <Link to={`/projects/${pid}/source`} className="underline">
              원고 보기
            </Link>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className={btn("secondary")} onClick={() => navigate(`/projects/${pid}/settings`)}>
            전체 다시 생성
          </button>
          <button type="button" className={btn("secondary")} onClick={() => setConfirmRerun(true)} disabled={rerun.isPending || Boolean(running)}>
            {rerun.isPending && <Spinner />}같은 조건으로 다시 생성
          </button>
          <ExportMenu projectId={pid} />
        </div>
      </div>

      {confirmRerun && (
        <Notice tone="warn">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>
              같은 조건으로 처음부터 다시 생성합니다. 새 결과가 현재 결과가 되며, 지금 결과와 수정 이력은 이전 실행으로 남습니다.
            </span>
            <span className="flex gap-2">
              <button type="button" className={btn("secondary", "sm")} onClick={() => setConfirmRerun(false)}>
                취소
              </button>
              <button
                type="button"
                className={btn("primary", "sm")}
                onClick={() => {
                  setConfirmRerun(false);
                  rerun.mutate();
                }}
              >
                다시 생성 시작
              </button>
            </span>
          </div>
        </Notice>
      )}
      <ErrorBox error={rerun.error} />

      {running && (
        <Notice>
          새 생성이 진행 중입니다.{" "}
          <Link to={`/runs/${latest!.id}`} className="font-medium underline">
            진행 상황 보기
          </Link>
        </Notice>
      )}
      {latest?.status === "failed" && (hasOutline || p.manual) && (
        <Notice tone="warn">최근 생성(실행 {latest.id})이 실패해서 이전에 성공한 결과를 보여 주고 있습니다. {latest.error_message}</Notice>
      )}

      {!hasOutline && !p.manual ? (
        <Card>
          <p className="text-sm text-slate-600">아직 생성된 결과가 없습니다. 원고를 넣고 조건을 정한 뒤 생성해 주세요.</p>
          <div className="mt-3 flex gap-2">
            <Link to={`/projects/${pid}/source`} className={btn("secondary")}>
              자료 입력
            </Link>
            <Link to={`/projects/${pid}/settings`} className={btn("primary")}>
              조건 설정
            </Link>
          </div>
        </Card>
      ) : (
        <>
          {/* ---------- 탭 ---------- */}
          <div role="tablist" className="flex gap-1 border-b border-slate-200">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => setView({ tab: t.key })}
                className={`-mb-px border-b-2 px-4 py-2 text-sm ${
                  tab === t.key ? "border-indigo-600 font-semibold text-indigo-700" : "border-transparent text-slate-600 hover:text-slate-900"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* ---------- 탭 내용 ---------- */}
          {tab === "outline" &&
            (outline.data ? (
              <OutlineTab projectId={pid} outline={outline.data} onOpenScene={(id) => setView({ tab: "storyboard", scene: id })} />
            ) : (
              <Notice>구성안이 없습니다. 영상형이나 둘 다로 생성하면 구성안과 스토리보드가 만들어집니다.</Notice>
            ))}

          {(tab === "storyboard" || tab === "narration") &&
            (outline.data ? (
              // 와이어프레임의 세 칸. 넓은 화면에서는 왼쪽 240px, 오른쪽 320px로 고정하고 가운데를 넓게 쓴다.
              <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)_320px]">
                <aside className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)] lg:self-start lg:overflow-auto">
                  <SceneList
                    projectId={pid}
                    runId={runId}
                    outline={outline.data}
                    selectedId={selected?.id ?? null}
                    onSelect={(id) => setView({ scene: id })}
                  />
                </aside>
                <section className="space-y-4">
                  <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                    {selected ? (
                      // key로 장면 id를 주어, 다른 장면을 고르면 편집기가 새로 만들어져 이전 장면의 편집 값이 섞이지 않게 한다.
                      <SceneEditor
                        key={selected.id}
                        projectId={pid}
                        runId={runId}
                        scene={selected}
                        mode={tab === "narration" ? "narration" : "full"}
                      />
                    ) : (
                      <p className="text-sm text-slate-500">장면이 없습니다. 왼쪽 아래 "+ 장면 추가"로 장면을 만들 수 있습니다.</p>
                    )}
                  </div>
                  {tab === "narration" && (
                    <Card title="전체 자막">
                      <NarrationTimeline outline={outline.data} selectedId={selected?.id ?? null} onSelect={(id) => setView({ scene: id })} />
                    </Card>
                  )}
                </section>
                <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)] lg:self-start lg:overflow-auto">
                  <CheckPanel runId={runId} checks={checks.data} isLoading={checks.isLoading} scene={selected} />
                  <ErrorBox error={checks.error} className="mt-2" />
                </aside>
              </div>
            ) : (
              <Notice>구성안이 없습니다. 영상형이나 둘 다로 생성하면 스토리보드와 내레이션이 만들어집니다.</Notice>
            ))}

          {tab === "manual" && <ManualTab projectId={pid} runId={runId} checks={checks.data} />}

          {tab === "checks" &&
            (runId && checks.data ? (
              <ChecksTab projectId={pid} runId={runId} checks={checks.data} outline={outline.data} />
            ) : checks.isError ? (
              <ErrorBox error={checks.error} />
            ) : (
              <Loading text="검수 결과를 불러오는 중입니다." />
            ))}
        </>
      )}

      {/* 단계 7: 수정 요청 에이전트 */}
      <EditRequestPanel projectId={pid} runId={runId} />
    </div>
  );
}
