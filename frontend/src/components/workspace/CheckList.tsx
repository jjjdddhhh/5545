// CheckList.tsx : 검수 항목 목록과 사람 확인 체크박스.
// 결과 작업공간의 오른쪽 검수 패널과 "검수" 탭이 함께 쓴다.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { qk, setHumanCheck } from "../../api/endpoints";
import type { CheckItem, ChecksView } from "../../api/types";
import { RESULT_LABEL } from "../../lib/labels";
import { ErrorBox, StatusDot } from "../ui";

/**
 * 자동 검수 항목 목록. 항목마다 상태 점, 코드와 이름, 결과 메시지를 한 줄씩 보여 준다.
 * items: 보여 줄 항목. compact가 참이면 오른쪽 패널처럼 좁은 칸에 맞게 코드를 숨긴다.
 */
export function AutoCheckList({ items, compact = false, empty }: { items: CheckItem[]; compact?: boolean; empty?: string }) {
  if (items.length === 0) return <p className="text-xs text-slate-500">{empty ?? "검수 항목이 없습니다."}</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((c) => (
        <li key={c.id} className="flex items-start gap-2 text-sm">
          <StatusDot status={c.result} className="mt-1.5" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-1.5">
              {!compact && <span className="font-mono text-xs text-slate-400">{c.check_code}</span>}
              <span className="font-medium text-slate-800">{c.label || c.check_code}</span>
              <span
                className={`text-xs ${c.result === "fail" ? "text-red-600" : c.result === "warn" ? "text-orange-600" : "text-slate-500"}`}
              >
                {RESULT_LABEL[c.result] ?? c.result}
              </span>
            </div>
            {c.message && <p className="text-xs leading-snug text-slate-600">{c.message}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * 사람 확인 체크박스 세 개(H01 원고 의도 반영, H02 대상 수준 적합, H03 제작 가능성).
 * 체크하면 PUT /api/runs/{run_id}/human-checks/{code}를 부르고, 응답(ChecksView 전체)으로 검수 캐시를 바로 바꾼다.
 * 응답이 검수 결과 전체를 담고 있으므로 다시 조회할 필요가 없어 invalidate 대신 setQueryData를 쓴다.
 */
export function HumanChecks({ runId, items }: { runId: number; items: CheckItem[] }) {
  const queryClient = useQueryClient();
  // 누른 즉시 체크 표시를 바꿔 두는 낙관적 값(코드별). 응답이 오면 지운다.
  // 요청 상태(isPending)는 한 박자 늦게 반영되어 그 사이 체크가 잠깐 풀려 보이므로, 클릭 순간에 바로 쓰는 값을 따로 둔다.
  const [optimistic, setOptimistic] = useState<Record<string, boolean>>({});
  const toggle = useMutation({
    mutationFn: ({ code, checked }: { code: string; checked: boolean }) => setHumanCheck(runId, code, checked),
    onSuccess: (view: ChecksView) => queryClient.setQueryData(qk.checks(runId), view),
    onSettled: (_data, _err, vars) =>
      setOptimistic((o) => {
        const next = { ...o };
        delete next[vars.code];
        return next;
      }),
  });

  return (
    <div>
      <ul className="space-y-1.5">
        {items.map((c) => {
          const checked = c.result === "pass";
          const shown = optimistic[c.check_code] ?? checked;
          return (
            <li key={c.id}>
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-indigo-600"
                  checked={shown}
                  disabled={toggle.isPending}
                  onChange={(e) => {
                    const value = e.target.checked;
                    setOptimistic((o) => ({ ...o, [c.check_code]: value }));
                    toggle.mutate({ code: c.check_code, checked: value });
                  }}
                />
                <span className="font-mono text-xs text-slate-400">{c.check_code}</span>
                <span className="text-slate-800">{c.label}</span>
                {c.checked_at && checked && (
                  <span className="ml-auto text-[10px] text-slate-400">
                    {new Date(c.checked_at).toLocaleDateString("ko-KR")}
                  </span>
                )}
              </label>
            </li>
          );
        })}
      </ul>
      <ErrorBox error={toggle.error} className="mt-2" />
    </div>
  );
}
