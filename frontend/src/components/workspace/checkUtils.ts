// checkUtils.ts : 검수 항목을 화면 영역별로 나누는 함수.
// 백엔드 검수 결과(review_check)는 target_type과 target_id로 무엇에 걸린 결과인지 알려 준다.
// target_type 종류(backend/app/pipeline/checks.py 기준):
// - scene: 장면(target_id는 장면 id)
// - narration, subtitle: 내레이션과 그 자막(target_id는 내레이션 id)
// - manual_step: 매뉴얼 단계(target_id는 단계 id)
// - outline, manual, run: 구성안 전체, 매뉴얼 전체, 실행 전체에 걸린 결과(target_id 없음)
import type { CheckItem, SceneOut } from "../../api/types";

/** 실행 전체에 걸린 결과인지. 장면이나 단계 하나가 아니라 구성안·매뉴얼·실행 단위로 걸린 항목이다. */
export function isRunLevel(c: CheckItem): boolean {
  return c.target_type === null || c.target_type === "run" || c.target_type === "outline" || c.target_type === "manual";
}

/**
 * 장면 하나에 걸린 자동 검수 항목.
 * 장면 자체(scene)뿐 아니라 그 장면의 내레이션·자막(narration, subtitle) 결과도 장면의 결과로 본다.
 * 백엔드 views.scene_check_status가 장면 점 색을 정할 때 쓰는 규칙과 같다.
 */
export function checksForScene(items: CheckItem[], scene: SceneOut): CheckItem[] {
  const narrId = scene.narration?.id;
  return items.filter(
    (c) =>
      (c.target_type === "scene" && c.target_id === scene.id) ||
      ((c.target_type === "narration" || c.target_type === "subtitle") && narrId !== undefined && c.target_id === narrId),
  );
}

/** 매뉴얼 단계 하나에 걸린 자동 검수 항목. */
export function checksForStep(items: CheckItem[], stepId: number): CheckItem[] {
  return items.filter((c) => c.target_type === "manual_step" && c.target_id === stepId);
}

/** 통과율을 "87%"처럼 바꾼다. 결과가 하나도 없으면(null) "-"다. */
export function formatRate(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "-" : `${Math.round(rate * 100)}%`;
}
