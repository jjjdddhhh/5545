// endpoints.ts : 백엔드 API 하나하나를 부르는 함수와 TanStack Query 키.
// 화면 컴포넌트는 경로 문자열을 직접 쓰지 않고 이 파일의 함수만 부른다. 경로가 바뀌면 여기 한곳만 고치면 된다.
// 경로와 상태 코드는 backend/app/api/*.py의 라우터를 그대로 따랐다.
import { api } from "./client";
import type {
  ChecksView,
  EditRequestCreated,
  EditRequestOut,
  HealthView,
  ManualStepPatch,
  ManualView,
  OutlineView,
  ParagraphIn,
  ProposalOut,
  ProjectDetail,
  ProjectListItem,
  ProjectOut,
  RegenerateOut,
  RunBrief,
  RunCreated,
  SceneOut,
  ScenePatch,
  ScheduleItemPatch,
  SettingIn,
  SettingOut,
  SourceOut,
} from "./types";

/**
 * TanStack Query 키 모음.
 * 설계서 5절 "수정 뒤에는 바뀐 쿼리만 무효화한다"를 지키려면 키를 한곳에서 같은 모양으로 만들어야 한다.
 * 예를 들어 장면을 고치면 qk.outline(pid)와 qk.checks(runId)만 무효화하고, 매뉴얼 쿼리는 건드리지 않는다.
 */
export const qk = {
  health: ["health"] as const,
  projects: (q: string) => ["projects", q] as const,
  projectsAll: ["projects"] as const,
  project: (id: number) => ["project", id] as const,
  sourceLatest: (id: number) => ["source", id] as const,
  settings: (id: number) => ["settings", id] as const,
  outline: (id: number) => ["outline", id] as const,
  manual: (id: number) => ["manual", id] as const,
  checks: (runId: number) => ["checks", runId] as const,
  run: (runId: number) => ["run", runId] as const,
  editRequests: (projectId: number) => ["edit-requests", projectId] as const,
  proposals: (editRequestId: number) => ["proposals", editRequestId] as const,
};

// ---------- 상태 확인 ----------
export const getHealth = () => api.get<HealthView>("/api/health");

// ---------- 프로젝트 ----------

/** 프로젝트 목록. q가 있으면 제목 검색이다. 한글 검색어는 encodeURIComponent로 감싸 보낸다. */
export const listProjects = (q: string) =>
  api.get<ProjectListItem[]>(`/api/projects${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
export const createProject = (title: string) => api.post<ProjectOut>("/api/projects", { title });
export const getProject = (id: number) => api.get<ProjectDetail>(`/api/projects/${id}`);

// ---------- 원고 ----------

/**
 * 원고 올리기. 붙여넣은 글은 text, 파일은 file 필드로 보낸다(multipart/form-data).
 * 둘 다 오면 서버가 파일을 쓰므로 화면에서는 한쪽만 보낸다.
 */
export const uploadSource = (projectId: number, input: { text?: string; file?: File }) => {
  const form = new FormData();
  if (input.file) form.append("file", input.file);
  else if (input.text !== undefined) form.append("text", input.text);
  return api.post<SourceOut>(`/api/projects/${projectId}/sources`, form);
};
/** 마지막 원고. 아직 없으면 404를 받는다. */
export const getLatestSource = (projectId: number) => api.get<SourceOut>(`/api/projects/${projectId}/sources/latest`);
/** 문단 저장. 이미 생성에 쓴 원고면 서버가 새 원고 행을 만들므로 응답의 id가 바뀔 수 있다. */
export const saveParagraphs = (sourceId: number, paragraphs: ParagraphIn[]) =>
  api.put<SourceOut>(`/api/sources/${sourceId}/paragraphs`, { paragraphs });

// ---------- 생성 조건 ----------
export const getSettings = (projectId: number) => api.get<SettingOut>(`/api/projects/${projectId}/settings`);
export const saveSettings = (projectId: number, body: SettingIn) =>
  api.put<SettingOut>(`/api/projects/${projectId}/settings`, body);

// ---------- 생성 실행 ----------
/** 생성 시작. 202와 run_id만 바로 돌아오고, 진행은 SSE(/api/runs/{id}/events)로 본다. */
export const startRun = (projectId: number) => api.post<RunCreated>(`/api/projects/${projectId}/runs`);
export const getRun = (runId: number) => api.get<RunBrief>(`/api/runs/${runId}`);

// ---------- 구성안과 장면 ----------
export const getOutline = (projectId: number) => api.get<OutlineView>(`/api/projects/${projectId}/outline`);
export const patchScene = (sceneId: number, body: ScenePatch) => api.patch<SceneOut>(`/api/scenes/${sceneId}`, body);
/** 내레이션 수정. 서버가 자막을 코드로 즉시 다시 나누고, 장면 전체(SceneOut)를 돌려준다. */
export const patchNarration = (narrationId: number, body: string) =>
  api.patch<SceneOut>(`/api/narrations/${narrationId}`, { body });
/** 한 장면만 다시 생성. LLM을 부르는 동기 API라 수십 초 걸릴 수 있고, 모델 오류는 502로 온다. */
export const regenerateScene = (sceneId: number) =>
  api.post<RegenerateOut>(`/api/scenes/${sceneId}/regenerate`, { parts: ["detail", "narration"] });
export const reorderScenes = (projectId: number, sceneIds: number[]) =>
  api.put<OutlineView>(`/api/projects/${projectId}/scene-order`, { scene_ids: sceneIds });
export const addScene = (projectId: number, title: string) =>
  api.post<SceneOut>(`/api/projects/${projectId}/scenes`, { title });

// ---------- 매뉴얼과 일정 ----------
export const getManual = (projectId: number) => api.get<ManualView>(`/api/projects/${projectId}/manual`);
export const patchManualStep = (stepId: number, body: ManualStepPatch) =>
  api.patch<ManualView>(`/api/manual-steps/${stepId}`, body);
export const patchScheduleItem = (itemId: number, body: ScheduleItemPatch) =>
  api.patch<ManualView>(`/api/schedule-items/${itemId}`, body);

// ---------- 검수 ----------
export const getChecks = (runId: number) => api.get<ChecksView>(`/api/runs/${runId}/checks`);
export const recheck = (runId: number) => api.post<ChecksView>(`/api/runs/${runId}/checks/recheck`);
export const setHumanCheck = (runId: number, code: string, checked: boolean) =>
  api.put<ChecksView>(`/api/runs/${runId}/human-checks/${code}`, { checked });

// ---------- 수정 요청 에이전트(설계서 13절) ----------

/** 자연어 수정 요청 보내기. 202와 요청 id만 바로 돌아오고, 에이전트의 진행은 SSE(/api/edit-requests/{id}/events)로 본다. */
export const createEditRequest = (projectId: number, requestText: string) =>
  api.post<EditRequestCreated>(`/api/projects/${projectId}/edit-requests`, { request_text: requestText });
/** 프로젝트의 수정 요청 이력(최근 것부터 20개). 화면을 다시 열었을 때 마지막 요청을 이어서 보여 주는 데 쓴다. */
export const listEditRequests = (projectId: number) =>
  api.get<EditRequestOut[]>(`/api/projects/${projectId}/edit-requests`);
/** 요청 하나가 만든 변경 제안 목록(바뀌기 전과 후, 자막 미리보기, 제안 검수 결과 포함). */
export const getProposals = (editRequestId: number) =>
  api.get<ProposalOut[]>(`/api/edit-requests/${editRequestId}/proposals`);
/** 제안 승인. 제안을 만든 뒤 내용이 바뀌었으면 409가 온다. */
export const acceptProposal = (proposalId: number) => api.post<ProposalOut>(`/api/proposals/${proposalId}/accept`);
/** 제안 거절. 사유는 선택이며 서버가 요청 요약 끝에 남긴다. */
export const rejectProposal = (proposalId: number, reason?: string) =>
  api.post<ProposalOut>(`/api/proposals/${proposalId}/reject`, { reason: reason || null });
