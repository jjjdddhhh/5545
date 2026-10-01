// labels.ts : 화면에 보여 줄 한국어 이름과 작은 서식 함수.
// 백엔드는 상태와 종류를 영어 코드(done, heading 등)로 주므로, 화면에 보여 줄 한국어 이름을 이 파일 한곳에 모았다.

import type { ParagraphKind } from "../api/types";

/** 실행 상태 이름. 목록 화면의 최근 실행 배지와 진행 화면에 쓴다. */
export const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "대기",
  running: "진행 중",
  done: "완료",
  failed: "실패",
};

/** 단계 상태 이름. 진행 화면의 단계 목록에 쓴다. */
export const STAGE_STATUS_LABEL: Record<string, string> = {
  pending: "대기",
  running: "진행 중",
  done: "완료",
  failed: "실패",
};

/** 단계 키와 한국어 이름. backend runner.STAGES와 같은 순서다. snapshot이 오기 전이나 label이 없을 때 대신 쓴다. */
export const STAGE_LABEL: Record<string, string> = {
  clean: "텍스트 정제",
  budget: "분량 계산",
  outline: "구조화·구성안",
  scene_detail: "장면 상세",
  narration: "내레이션·자막",
  manual: "맞춤 매뉴얼·일정",
  checks: "검수",
  save: "저장",
};

/** 문단 종류 이름. text_cleaner가 정한 세 종류다. */
export const KIND_LABEL: Record<ParagraphKind, string> = {
  body: "본문",
  heading: "제목 후보",
  table: "표",
};

/** 콘텐츠 유형 이름. */
export const CONTENT_TYPE_LABEL: Record<string, string> = {
  video: "영상형",
  manual: "매뉴얼형",
  both: "둘 다",
};

/** 난이도 이름. */
export const DIFFICULTY_LABEL: Record<string, string> = {
  beginner: "초급",
  intermediate: "중급",
  advanced: "고급",
};

/** 검수 결과 이름. 사람 확인 항목의 unchecked는 "확인 전"으로 읽힌다. */
export const RESULT_LABEL: Record<string, string> = {
  pass: "통과",
  warn: "경고",
  fail: "실패",
  unchecked: "확인 전",
  none: "검수 전",
};

/** 주의사항 심각도 이름. */
export const SEVERITY_LABEL: Record<string, string> = {
  info: "참고",
  warning: "주의",
  danger: "위험",
};

/** 주의사항 출처 이름. rule은 검수 C10이 원고의 경고 문장에서 더한 것이라 "검수 추가"라고 보여 준다. */
export const CAUTION_SOURCE_LABEL: Record<string, string> = {
  ai: "AI 생성",
  rule: "검수 추가",
  user: "직접 추가",
};

/** 장면 필드 이름. "직접 수정함" 표시와 재생성 결과 안내에 쓴다. */
export const SCENE_FIELD_LABEL: Record<string, string> = {
  title: "제목",
  key_point: "학습 포인트",
  screen_description: "화면 설명",
  visual_suggestion: "시각자료 제안",
  on_screen_text: "화면 텍스트",
  narration: "내레이션",
  detail: "장면 상세",
};

/**
 * 밀리초를 "분:초.십분의일초" 모양으로 바꾼다. 자막 미리보기에 쓴다.
 * 예: 65300ms는 "1:05.3"이다. 자막은 1초보다 짧게 나뉘기도 해서 십분의 일 초까지 보여 준다.
 */
export function formatMs(ms: number): string {
  const totalTenths = Math.round(ms / 100);
  const minutes = Math.floor(totalTenths / 600);
  const seconds = Math.floor((totalTenths % 600) / 10);
  const tenths = totalTenths % 10;
  return `${minutes}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

/** 초를 "분:초" 모양으로 바꾼다. 장면 시작 시각과 전체 길이에 쓴다. 예: 125초는 "2:05"다. */
export function formatSec(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** ISO 시각 문자열을 "2026. 10. 1. 14:05" 같은 한국어 날짜·시각으로 바꾼다. 값이 없으면 빈 문자열이다. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}
