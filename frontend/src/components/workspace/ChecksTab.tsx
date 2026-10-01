// ChecksTab.tsx : 결과 작업공간의 "검수" 탭.
// 자동 검수 전체를 검사 코드(C01~C12)별로 묶어 보여 주고, 사람 확인 체크박스와 "다시 검수" 단추를 둔다.
// "다시 검수"는 POST /api/runs/{run_id}/checks/recheck로 코드 검수만 다시 돌린다(LLM은 부르지 않는다).
// 다시 검수하면 장면 목록의 점 색과 매뉴얼 단계의 검수 상태도 바뀌므로 구성안과 매뉴얼 쿼리도 함께 무효화한다.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { qk, recheck } from "../../api/endpoints";
import type { CheckItem, ChecksView, OutlineView } from "../../api/types";
import { Card, ErrorBox, Spinner, StatusDot, btn } from "../ui";
import { AutoCheckList, HumanChecks } from "./CheckList";
import { formatRate } from "./checkUtils";

interface Props {
  projectId: number;
  runId: number;
  checks: ChecksView;
  outline: OutlineView | undefined;
}

/** 검사 결과 목록에서 가장 나쁜 결과. 묶음 머리줄의 점 색으로 쓴다. 백엔드 views.worst와 같은 순서다. */
function worst(items: CheckItem[]): string {
  const rank: Record<string, number> = { pass: 1, unchecked: 1, warn: 2, fail: 3 };
  return items.reduce((w, c) => ((rank[c.result] ?? 0) > (rank[w] ?? 0) ? c.result : w), "none");
}

export default function ChecksTab({ projectId, runId, checks, outline }: Props) {
  const queryClient = useQueryClient();

  const re = useMutation({
    mutationFn: () => recheck(runId),
    onSuccess: (view) => {
      queryClient.setQueryData(qk.checks(runId), view);
      queryClient.invalidateQueries({ queryKey: qk.outline(projectId) });
      queryClient.invalidateQueries({ queryKey: qk.manual(projectId) });
    },
  });

  // 검사 코드별로 묶는다. 서버가 코드 순서로 정렬해 주므로 Map에 넣은 순서가 곧 화면 순서다.
  const groups = new Map<string, CheckItem[]>();
  checks.auto.forEach((c) => {
    const list = groups.get(c.check_code) ?? [];
    list.push(c);
    groups.set(c.check_code, list);
  });

  // 항목의 대상 이름. 장면이나 내레이션에 걸린 항목이면 "장면 3"처럼 어느 장면인지 붙여 준다.
  const sceneById = new Map(outline?.scenes.map((s) => [s.id, s]) ?? []);
  const sceneByNarr = new Map(outline?.scenes.filter((s) => s.narration).map((s) => [s.narration!.id, s]) ?? []);
  function targetName(c: CheckItem): string {
    if (c.target_type === "scene" && c.target_id) return `장면 ${sceneById.get(c.target_id)?.seq ?? "?"}`;
    if ((c.target_type === "narration" || c.target_type === "subtitle") && c.target_id) {
      const sc = sceneByNarr.get(c.target_id);
      return `장면 ${sc?.seq ?? "?"} ${c.target_type === "subtitle" ? "자막" : "내레이션"}`;
    }
    if (c.target_type === "manual_step") return "매뉴얼 단계";
    if (c.target_type === "outline") return "구성안";
    if (c.target_type === "manual") return "매뉴얼";
    return "전체";
  }

  const s = checks.summary;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <Card
        title="자동 검수"
        actions={
          <button type="button" className={btn("secondary", "sm")} onClick={() => re.mutate()} disabled={re.isPending}>
            {re.isPending && <Spinner className="h-3 w-3" />}다시 검수
          </button>
        }
      >
        <div className="mb-3 flex flex-wrap gap-3 text-sm">
          <span>
            통과율 <b>{formatRate(s.pass_rate)}</b>
          </span>
          <span className="text-emerald-700">통과 {s.pass}</span>
          <span className="text-orange-600">경고 {s.warn}</span>
          <span className="text-red-600">실패 {s.fail}</span>
          <span className="text-slate-500">전체 {s.total}</span>
        </div>
        <ErrorBox error={re.error} className="mb-2" />
        {groups.size === 0 ? (
          <p className="text-sm text-slate-500">자동 검수 결과가 없습니다.</p>
        ) : (
          <div className="space-y-3">
            {[...groups.entries()].map(([code, items]) => (
              <details key={code} open={worst(items) !== "pass"} className="rounded-md border border-slate-200">
                <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm">
                  <StatusDot status={worst(items)} />
                  <span className="font-mono text-xs text-slate-400">{code}</span>
                  <span className="font-medium">{items[0].label}</span>
                  <span className="ml-auto text-xs text-slate-500">{items.length}건</span>
                </summary>
                <div className="border-t border-slate-100 px-3 py-2">
                  <AutoCheckList
                    items={items.map((c) => ({ ...c, label: targetName(c) }))}
                    compact
                  />
                </div>
              </details>
            ))}
          </div>
        )}
      </Card>
      <Card title="사람 확인">
        <HumanChecks runId={runId} items={checks.human} />
        <p className="mt-2 text-xs text-slate-500">자동 검수로 확인할 수 없는 항목입니다. 결과를 직접 읽고 체크해 주세요.</p>
      </Card>
    </div>
  );
}
