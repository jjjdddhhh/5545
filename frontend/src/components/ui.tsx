// ui.tsx : 여러 화면이 함께 쓰는 작은 표시용 컴포넌트 모음.
// 상태 점, 배지, 오류 상자, 회전 표시(스피너), 버튼 스타일처럼 모양만 맡는 것들이다.
// UI 키트를 따로 들이지 않고 Tailwind 클래스만으로 만든 이유는 의존성을 줄이고, 프로토타입 화면을 고치기 쉽게 하기 위해서다.
import type { ReactNode } from "react";
import { RESULT_LABEL, RUN_STATUS_LABEL } from "../lib/labels";

/**
 * 버튼 클래스. variant별로 색만 다르다.
 * - primary: 화면에서 가장 중요한 동작(수정 저장, 내보내기, 생성 시작). 와이어프레임의 "강조" 버튼이다.
 * - secondary: 보조 동작(다시 생성, 취소 등).
 * - ghost: 표 안의 작은 동작(합치기, 나누기 등).
 */
export function btn(variant: "primary" | "secondary" | "ghost" | "danger" = "secondary", size: "sm" | "md" = "md"): string {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition disabled:cursor-not-allowed disabled:opacity-50";
  const sizes = { sm: "px-2 py-1 text-xs", md: "px-3.5 py-2 text-sm" };
  const variants = {
    primary: "bg-indigo-600 text-white shadow-sm hover:bg-indigo-700",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "border border-red-300 bg-white text-red-700 hover:bg-red-50",
  };
  return `${base} ${sizes[size]} ${variants[variant]}`;
}

/** 입력칸 공통 클래스. 모든 텍스트 입력과 선택 상자가 같은 모양을 쓰게 한다. */
export const inputCls =
  "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";

/** 검수 결과별 점 색. 와이어프레임대로 통과는 초록, 경고는 주황, 실패는 빨강, 검수 전은 회색이다. */
const DOT_COLOR: Record<string, string> = {
  pass: "bg-emerald-500",
  warn: "bg-orange-400",
  fail: "bg-red-500",
  unchecked: "bg-slate-300",
  none: "bg-slate-300",
};

/** 검수 상태 점. 마우스를 올리면 "통과", "경고" 같은 이름이 보인다(색만으로 구분하기 어려운 사용자를 위해). */
export function StatusDot({ status, className = "" }: { status: string; className?: string }) {
  return (
    <span
      title={RESULT_LABEL[status] ?? status}
      aria-label={RESULT_LABEL[status] ?? status}
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${DOT_COLOR[status] ?? "bg-slate-300"} ${className}`}
    />
  );
}

/** 일반 배지. tone으로 색을 고른다. */
export function Badge({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: "slate" | "indigo" | "green" | "orange" | "red" | "amber" | "sky";
}) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    indigo: "bg-indigo-100 text-indigo-700",
    green: "bg-emerald-100 text-emerald-700",
    orange: "bg-orange-100 text-orange-700",
    red: "bg-red-100 text-red-700",
    amber: "bg-amber-100 text-amber-800",
    sky: "bg-sky-100 text-sky-700",
  };
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** 실행 상태 배지. 목록 화면에서 프로젝트마다 최근 실행 상태를 보여 준다. 실행이 없으면 "생성 전"이다. */
export function RunStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge>생성 전</Badge>;
  const tone = status === "done" ? "green" : status === "failed" ? "red" : status === "running" ? "indigo" : "amber";
  return <Badge tone={tone}>{RUN_STATUS_LABEL[status] ?? status}</Badge>;
}

/** 회전 표시. 오래 걸리는 요청(장면 재생성 등)을 기다리는 동안 보여 준다. */
export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="처리 중"
      className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${className}`}
    />
  );
}

/** 오류 메시지 상자. error가 없으면 아무것도 그리지 않는다. Error 객체든 문자열이든 받는다. */
export function ErrorBox({ error, className = "" }: { error: unknown; className?: string }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className={`rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 ${className}`}>
      {message}
    </div>
  );
}

/** 안내 상자. 경고(warn)와 일반 안내(info) 두 가지 색이 있다. */
export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "success" }) {
  const tones = {
    info: "border-sky-200 bg-sky-50 text-sky-800",
    warn: "border-amber-200 bg-amber-50 text-amber-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  };
  return <div className={`rounded-md border px-3 py-2 text-sm ${tones[tone]}`}>{children}</div>;
}

/** 불러오는 중 표시. 페이지 전체를 채울 때 쓴다. */
export function Loading({ text = "불러오는 중입니다." }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <Spinner /> {text}
    </div>
  );
}

/** 카드 상자. 흰 바탕에 테두리를 둘러 영역을 나눈다. title이 있으면 머리줄을 그린다. */
export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** "직접 수정함" 표시. 사용자가 고친 필드는 재생성 때 덮어쓰지 않는다는 것을 알려 준다(설계서 10절 규칙 2). */
export function EditedMark() {
  return (
    <span
      title="사용자가 직접 고친 필드입니다. 장면을 다시 생성해도 이 값은 바뀌지 않습니다."
      className="ml-1.5 rounded bg-violet-100 px-1 py-px text-[10px] font-medium text-violet-700"
    >
      직접 수정함
    </span>
  );
}
