// budget.ts : 조건 설정 화면의 "미리보기"용 분량 계산.
// backend/app/pipeline/budget.py의 compute_budget, char_budget와 같은 규칙을 화면에서 그대로 계산한다.
// 실제 생성에 쓰는 값은 언제나 서버가 다시 계산하므로, 이 결과는 사용자가 조건을 고르는 동안 보여 주는 참고값이다.
// 규칙이 서버와 어긋나면 미리보기와 실제 결과가 달라지므로, budget.py를 고치면 이 파일도 함께 고쳐야 한다.

/** 장면 수 상한. backend config.MAX_SCENES(40)와 같은 값이다. */
export const MAX_SCENES = 40;
/** 목표 분량 상한(초). backend config.MAX_DURATION_SEC(장면 40개 * 60초)와 같은 값이다. */
export const MAX_DURATION_SEC = MAX_SCENES * 60;
/** 내레이션 글자 수 허용 오차. backend config.NARRATION_TOLERANCE(15%)와 같은 값이며, 검수 C04가 쓰는 범위다. */
export const NARRATION_TOLERANCE = 0.15;

/**
 * 파이썬 round()와 같은 반올림(가운데 값은 짝수 쪽으로 보내는 은행가 반올림).
 * JavaScript의 Math.round는 2.5를 3으로 올리지만 파이썬 round(2.5)는 2다.
 * 예: 75초를 30초로 나누면 2.5인데, 서버는 2장면을 만든다. 미리보기가 3장면이라고 하면 사용자가 헷갈리므로 맞춘다.
 */
export function pyRound(x: number): number {
  const floor = Math.floor(x);
  const diff = x - floor;
  // 부동소수점 오차(예: 2.4999999)를 감안해 아주 작은 차이는 가운데 값으로 본다.
  if (Math.abs(diff - 0.5) < 1e-9) {
    return floor % 2 === 0 ? floor : floor + 1;
  }
  return Math.round(x);
}

/** 장면 시간 동안 읽을 수 있는 글자 수(공백 제외). budget.char_budget와 같고, 최소 1자다. */
export function charBudget(durationSec: number, cpm: number): number {
  return Math.max(1, pyRound((durationSec * cpm) / 60));
}

/** total을 n개의 정수로 고르게 나눈다. 나머지는 앞 장면부터 1씩 더한다(budget.split_evenly). */
export function splitEvenly(total: number, n: number): number[] {
  const base = Math.floor(total / n);
  const rest = total % n;
  return Array.from({ length: n }, (_, i) => base + (i < rest ? 1 : 0));
}

/** 미리보기 결과. 입력이 모자라면 null을 돌려준다. */
export interface BudgetPreview {
  sceneCount: number;
  totalSec: number;
  durations: number[];
  charBudgets: number[];
}

/**
 * budget.compute_budget와 같은 규칙.
 * 1. 장면 수가 없으면 목표 분량을 장면당 기본 시간으로 나눠 반올림하고, 1~40 사이로 자른다.
 * 2. 장면 수만 있으면 전체 분량은 장면 수 * 장면당 기본 시간이다.
 * 3. 둘 다 있으면 목표 분량을 그 장면 수로 고르게 나눈다.
 * 4. 장면마다 1초는 있어야 하므로 전체 분량이 장면 수보다 작으면 장면 수로 올린다.
 */
export function computeBudget(
  targetDurationSec: number | null,
  sceneCount: number | null,
  sceneDefaultSec: number,
  narrationCpm: number,
): BudgetPreview | null {
  if (targetDurationSec === null && sceneCount === null) return null;
  if (!(sceneDefaultSec > 0) || !(narrationCpm > 0)) return null;

  let n: number;
  let total: number;
  if (sceneCount === null) {
    n = Math.min(Math.max(1, pyRound((targetDurationSec as number) / sceneDefaultSec)), MAX_SCENES);
    total = targetDurationSec as number;
  } else {
    n = Math.min(Math.max(1, sceneCount), MAX_SCENES);
    total = targetDurationSec !== null ? targetDurationSec : n * sceneDefaultSec;
  }
  total = Math.max(total, n);
  const durations = splitEvenly(total, n);
  return {
    sceneCount: n,
    totalSec: total,
    durations,
    charBudgets: durations.map((d) => charBudget(d, narrationCpm)),
  };
}

/** 내레이션 글자 수. 공백(띄어쓰기, 줄바꿈)은 읽지 않으므로 빼고 센다(budget.count_chars). */
export function countChars(text: string): number {
  let n = 0;
  for (const ch of text) {
    if (!/\s/.test(ch)) n += 1;
  }
  return n;
}

/** 예산의 ±15% 범위. 검수 C04와 같은 경계이며, 경계값은 통과로 본다. */
export function toleranceRange(budget: number): { min: number; max: number } {
  return {
    min: Math.ceil(budget * (1 - NARRATION_TOLERANCE)),
    max: Math.floor(budget * (1 + NARRATION_TOLERANCE)),
  };
}
