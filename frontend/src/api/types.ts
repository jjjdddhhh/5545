// types.ts : 백엔드 API 응답과 요청 본문의 타입.
// backend/app/api/schemas.py의 Pydantic 모델을 그대로 옮겼다. 설계서 6절에 따라 백엔드 스키마(OpenAPI 문서)가 계약서이므로,
// 백엔드 스키마가 바뀌면 이 파일도 같은 이름과 같은 모양으로 고쳐야 한다.
// 날짜·시각(datetime)은 JSON으로 올 때 ISO 문자열이므로 string으로 둔다.

// ---------- 프로젝트 ----------

/** 실행 상태. queued는 대기, running은 진행 중, done은 완료, failed는 실패다. */
export type RunStatus = "queued" | "running" | "done" | "failed";

/** 목록과 상세 화면에 보여 줄 실행 요약(schemas.RunBrief). */
export interface RunBrief {
  id: number;
  status: RunStatus;
  current_stage: string | null;
  llm_model: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

/** 프로젝트 기본 정보(schemas.ProjectOut). status는 draft, generating, ready, error 가운데 하나다. */
export interface ProjectOut {
  id: number;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

/** 목록 화면의 한 줄. 최근 실행 상태 배지를 그리려고 latest_run을 함께 받는다(schemas.ProjectListItem). */
export interface ProjectListItem extends ProjectOut {
  latest_run: RunBrief | null;
}

/** 구성안 요약. projects.get_project가 run_id까지 넣어 준다. */
export interface OutlineBrief {
  id: number;
  title: string;
  scene_count: number;
  run_id: number;
}

/** 매뉴얼 요약. projects.get_project가 run_id까지 넣어 준다. */
export interface ManualBrief {
  id: number;
  title: string;
  step_count: number;
  run_id: number;
}

/** 최근 원고 요약. 원문 전체가 필요하면 GET /sources/latest를 따로 부른다. */
export interface SourceBrief {
  id: number;
  char_count: number;
  paragraph_count: number;
  file_name: string | null;
}

/** GET /api/projects/{id}: 프로젝트 정보와 최신 결과 요약(schemas.ProjectDetail). */
export interface ProjectDetail extends ProjectOut {
  source: SourceBrief | null;
  setting: SettingOut | null;
  latest_run: RunBrief | null;
  outline: OutlineBrief | null;
  manual: ManualBrief | null;
}

// ---------- 원고 ----------

/** text_cleaner가 만드는 문단 종류. body는 본문, heading은 제목 후보, table은 표다. */
export type ParagraphKind = "body" | "heading" | "table";

/** 번호가 붙은 문단 하나. id(p1, p2...)는 근거 추적에 쓴다. */
export interface Paragraph {
  id: string;
  kind: ParagraphKind;
  text: string;
}

/** 문단 저장 요청의 한 줄. 번호는 서버가 다시 매기므로 보내지 않는다(schemas.ParagraphIn). */
export interface ParagraphIn {
  kind: ParagraphKind;
  text: string;
}

/** 원고 비교 미리보기(schemas.SourceOut). stats와 warnings는 업로드 직후 응답에서만 정확하다. */
export interface SourceOut {
  id: number;
  project_id: number;
  source_type: string;
  file_name: string | null;
  raw_text: string;
  clean_text: string;
  paragraphs: Paragraph[];
  char_count: number;
  created_at: string;
  stats: Record<string, number>;
  warnings: string[];
}

// ---------- 생성 조건 ----------

export type ContentType = "video" | "manual" | "both";
export type Difficulty = "beginner" | "intermediate" | "advanced";

/** 조건 설정 저장 요청(schemas.SettingIn). 목표 분량과 장면 수 가운데 하나는 반드시 있어야 한다. */
export interface SettingIn {
  content_type: ContentType;
  audience: string;
  difficulty: Difficulty;
  target_duration_sec: number | null;
  scene_count: number | null;
  output_language: string;
  tone: string | null;
  keywords: string[];
  narration_cpm: number;
  scene_default_sec: number;
  subtitle_max_chars: number;
}

/** 저장된 조건(schemas.SettingOut). */
export interface SettingOut {
  id: number;
  project_id: number;
  content_type: ContentType;
  audience: string;
  difficulty: Difficulty;
  target_duration_sec: number | null;
  scene_count: number | null;
  output_language: string;
  tone: string | null;
  keywords: string[] | null;
  narration_cpm: number;
  scene_default_sec: number;
  subtitle_max_chars: number;
  created_at: string;
}

// ---------- 생성 실행 ----------

/** POST /runs의 202 응답. 진행은 SSE로 따로 본다. */
export interface RunCreated {
  run_id: number;
}

/** 단계 하나의 상태. pending은 대기, running은 진행 중, done은 완료, failed는 실패다. */
export type StageStatus = "pending" | "running" | "done" | "failed";

/** 단계별 LLM 호출 통계(runner.run_snapshot의 stats). 코드 단계도 한 줄씩 기록되므로 calls가 1일 수 있다. */
export interface StageStats {
  calls: number;
  ok: number;
  retry: number;
  failed: number;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
}

/** snapshot 이벤트 안의 단계 하나. */
export interface SnapshotStage {
  key: string;
  label: string;
  status: StageStatus;
  stats: StageStats | null;
  /** 끝난 단계의 걸린 시간(ms). 아직 안 끝난 단계는 null이다. stage_done을 놓쳤을 때 이 값을 쓴다. */
  latency_ms: number | null;
}

/** SSE의 첫 이벤트. DB만 보고 다시 만든 실행 상태라 언제나 믿을 수 있는 기준 상태다. */
export interface SnapshotEvent {
  type: "snapshot";
  run_id: number;
  project_id: number;
  status: RunStatus;
  current_stage: string | null;
  error_message: string | null;
  llm_model: string;
  stages: SnapshotStage[];
}

export interface RunStartEvent {
  type: "run_start";
  run_id: number;
  stages: { key: string; label: string }[];
}

export interface StageStartEvent {
  type: "stage_start";
  stage: string;
  label: string;
  index: number;
  total: number;
}

export interface StageDoneEvent {
  type: "stage_done";
  stage: string;
  label: string;
  index: number;
  total: number;
  latency_ms: number;
  detail: Record<string, unknown>;
}

/** 장면 상세와 내레이션 단계에서 장면 하나를 시작할 때 오는 진행 이벤트. */
export interface ProgressEvent {
  type: "progress";
  stage: string;
  current: number;
  total: number;
  scene_id: number;
  title: string;
}

/** LLM 호출 시도 하나의 기록. status는 ok, retry, failed 가운데 하나다. */
export interface LlmCallEvent {
  type: "llm_call";
  stage: string;
  attempt: number | null;
  status: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  truncation_risk: boolean;
  target: unknown;
}

export interface ChecksEvent {
  type: "checks";
  summary: CheckSummary;
}

export interface StageErrorEvent {
  type: "stage_error";
  stage: string | null;
  label: string | null;
  message: string;
  trace?: string;
}

export interface DoneEvent {
  type: "done";
  run_id: number;
  status: "done" | "failed";
  message?: string | null;
}

// ---------- 구성안과 장면 ----------

/** 자막 한 줄. 시각은 장면 시작 기준 밀리초다. body에는 줄바꿈이 들어 있을 수 있다(최대 2줄). */
export interface CueOut {
  id: number;
  seq: number;
  start_ms: number;
  end_ms: number;
  body: string;
}

/** 내레이션. char_count는 공백을 뺀 글자 수다. */
export interface NarrationOut {
  id: number;
  body: string;
  char_count: number;
  est_duration_sec: number;
  is_edited: boolean;
}

/** 검수 상태 점 색. 장면에 걸린 자동 검수 결과 가운데 가장 나쁜 것이다. */
export type CheckStatus = "pass" | "warn" | "fail" | "none" | "unchecked";

/** 장면 하나(schemas.SceneOut). */
export interface SceneOut {
  id: number;
  seq: number;
  title: string;
  key_point: string;
  source_paragraphs: string[];
  screen_description: string | null;
  visual_suggestion: string | null;
  on_screen_text: string | null;
  duration_sec: number;
  char_budget: number;
  edited_fields: string[];
  start_sec: number;
  narration: NarrationOut | null;
  cues: CueOut[];
  check_status: CheckStatus;
}

export interface OutlineInfo {
  id: number;
  run_id: number;
  title: string;
  summary: string;
  learning_objectives: string[];
  created_at: string;
}

/** GET /api/projects/{id}/outline 응답. */
export interface OutlineView {
  outline: OutlineInfo;
  scenes: SceneOut[];
  total_sec: number;
}

/** 장면 수정 요청. 바꾼 필드만 보낸다(schemas.ScenePatch). */
export interface ScenePatch {
  title?: string;
  key_point?: string;
  screen_description?: string;
  visual_suggestion?: string;
  on_screen_text?: string;
}

/** 장면 재생성 응답. kept는 사용자가 고쳐서 그대로 둔 필드다. */
export interface RegenerateOut {
  scene: SceneOut;
  regenerated: string[];
  kept: string[];
}

// ---------- 매뉴얼과 일정 ----------

export interface ManualStepOut {
  id: number;
  seq: number;
  title: string;
  instruction: string;
  tip: string | null;
  source_paragraphs: string[];
  edited_fields: string[];
  check_status: CheckStatus;
}

/** 주의사항. source는 ai(모델), rule(검수 C10이 더한 것), user(사용자) 가운데 하나다. */
export interface CautionOut {
  id: number;
  severity: "info" | "warning" | "danger" | string;
  body: string;
  source: string;
}

/** 일정 항목. start_offset_day는 0부터 세므로 화면에는 1을 더해 "N일째"로 보여 준다. */
export interface ScheduleItemOut {
  id: number;
  seq: number;
  manual_step_id: number | null;
  title: string;
  start_offset_day: number;
  duration_days: number;
  interval_days: number | null;
  note: string | null;
  source: string;
}

export interface ManualInfo {
  id: number;
  run_id: number;
  audience: string;
  difficulty: string;
  title: string;
  intro: string | null;
  created_at: string;
}

/** GET /api/projects/{id}/manual 응답. 매뉴얼 단계와 일정 수정 API도 이 모양 전체를 돌려준다. */
export interface ManualView {
  manual: ManualInfo;
  steps: ManualStepOut[];
  cautions: CautionOut[];
  schedule: ScheduleItemOut[];
  total_days: number;
}

export interface ManualStepPatch {
  title?: string;
  instruction?: string;
  tip?: string;
}

/** 일정 수정 요청. interval_days에 0을 보내면 반복 없음으로 바뀐다. */
export interface ScheduleItemPatch {
  title?: string;
  duration_days?: number;
  interval_days?: number;
  note?: string;
}

// ---------- 검수 ----------

/** 검수 항목 하나. 사람 확인 항목(H01~H03)은 체크하면 result가 pass, 풀면 unchecked가 된다. */
export interface CheckItem {
  id: number;
  check_code: string;
  label: string;
  target_type: string | null;
  target_id: number | null;
  result: "pass" | "warn" | "fail" | "unchecked" | string;
  message: string | null;
  checked_by: number | null;
  checked_at: string | null;
}

/** 자동 항목만 센 요약. 결과가 하나도 없으면 pass_rate가 null이다. */
export interface CheckSummary {
  pass: number;
  warn: number;
  fail: number;
  total: number;
  pass_rate: number | null;
}

export interface ChecksView {
  run_id: number;
  summary: CheckSummary;
  auto: CheckItem[];
  human: CheckItem[];
}

// ---------- 상태 확인 ----------

/** GET /api/health 응답. 하나가 실패해도 500이 아니라 ok:false와 detail로 온다. */
export interface HealthView {
  db: { ok: boolean; version?: string; detail?: string };
  ollama: { ok: boolean; model: string; models?: string[]; model_ready?: boolean; detail?: string };
}

// ---------- 수정 요청 에이전트(schemas.py 수정 요청 부분, 설계서 13절) ----------

/** 수정 요청 상태. running(처리 중), proposed(제안 있음), refused(제안 없이 끝남), limit(도구 호출 한도), failed(실패), done(제안을 모두 처리함). */
export type EditStatus = "running" | "proposed" | "refused" | "limit" | "failed" | "done";

/** 에이전트가 부른 도구 하나(agent_action 한 줄). status의 blocked는 가드레일이 막은 호출이다. */
export interface AgentActionOut {
  id?: number;
  seq: number;
  tool_name: string;
  label: string;
  arguments: Record<string, unknown> | unknown[] | null;
  result_summary: string | null;
  status: "ok" | "error" | "blocked";
  latency_ms: number | null;
}

/** 수정 요청 한 건과 지금까지의 도구 호출 목록(schemas.EditRequestOut). */
export interface EditRequestOut {
  id: number;
  project_id: number;
  request_text: string;
  status: EditStatus;
  tool_calls: number;
  summary: string | null;
  llm_model: string;
  created_at: string;
  finished_at: string | null;
  actions: AgentActionOut[];
}

export interface EditRequestCreated {
  edit_request_id: number;
}

/** 제안 검수 결과 한 줄. 통과하면 code가 "ALL"인 한 줄만 온다. */
export interface ProposalCheck {
  code: string;
  result: string;
  message: string;
}

/** 변경 제안 하나(schemas.ProposalOut). before_value와 after_value를 나란히 보여 주고 승인이나 거절을 받는다. */
export interface ProposalOut {
  id: number;
  edit_request_id: number;
  target_type: "scene" | "narration" | "manual_step";
  target_id: number;
  field_name: string;
  field_label: string;
  target_label: string;
  scene_id: number | null;
  before_value: string | null;
  after_value: string;
  current_value: string | null;
  stale: boolean;
  reason: string | null;
  user_edited: boolean;
  status: "pending" | "accepted" | "rejected";
  decided_at: string | null;
  subtitle_preview: string[];
  checks: { ok?: boolean; results?: ProposalCheck[] };
}

/** 수정 요청 SSE 이벤트. 처음에는 snapshot(요청 전체), 그다음 도구마다 tool, 끝나면 done이 온다. */
export interface EditSnapshotEvent extends EditRequestOut {
  type: "snapshot";
}
export interface EditToolEvent extends AgentActionOut {
  type: "tool";
}
export interface EditDoneEvent {
  type: "done";
  status: EditStatus;
  summary: string | null;
}
