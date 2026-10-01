// CheckPanel.tsx : 결과 작업공간 오른쪽 칸의 검수 패널(와이어프레임 오른쪽 칸).
// 위쪽 "자동 검수"에는 선택한 장면에 걸린 항목과 실행 전체에 걸린 항목을 상태 점과 함께 보여 주고,
// 아래쪽 "사람 확인"에는 체크박스 세 개(H01~H03)를 둔다.
// 전체 항목을 다 보여 주면 좁은 칸이 길어지므로, 장면 편집 중에는 그 장면과 관련된 것만 추려 보여 준다.
// 전체 목록은 "검수" 탭에서 볼 수 있다.
import type { ChecksView, SceneOut } from "../../api/types";
import { AutoCheckList, HumanChecks } from "./CheckList";
import { checksForScene, formatRate, isRunLevel } from "./checkUtils";

interface Props {
  runId: number | null;
  checks: ChecksView | undefined;
  isLoading: boolean;
  scene: SceneOut | null;
}

export default function CheckPanel({ runId, checks, isLoading, scene }: Props) {
  if (!runId) return <p className="text-sm text-slate-500">검수할 실행이 없습니다.</p>;
  if (isLoading || !checks) return <p className="text-sm text-slate-500">검수 결과를 불러오는 중입니다.</p>;

  // 같은 검사(예: 출력 언어 C11)가 장면 필드와 내레이션에 각각 걸리면 이름이 겹쳐 보이므로, 대상이 장면이 아니면 이름 뒤에 붙여 준다.
  const TARGET_SUFFIX: Record<string, string> = { narration: " · 내레이션", subtitle: " · 자막" };
  const sceneItems = scene
    ? checksForScene(checks.auto, scene).map((c) => ({ ...c, label: `${c.label}${TARGET_SUFFIX[c.target_type ?? ""] ?? ""}` }))
    : [];
  const runItems = checks.auto.filter(isRunLevel);
  const s = checks.summary;

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-800">자동 검수</h2>
          <span className="text-xs text-slate-500">
            통과율 <b className="text-slate-800">{formatRate(s.pass_rate)}</b> · 경고 {s.warn} · 실패 {s.fail}
          </span>
        </div>
        {scene && (
          <div className="mb-3">
            <h3 className="mb-1 text-xs font-medium text-slate-500">장면 {scene.seq}</h3>
            <AutoCheckList items={sceneItems} compact empty="이 장면에 걸린 검수 항목이 없습니다." />
          </div>
        )}
        <h3 className="mb-1 text-xs font-medium text-slate-500">전체</h3>
        <AutoCheckList items={runItems} compact />
      </div>
      <div className="border-t border-slate-100 pt-3">
        <h2 className="mb-2 text-sm font-semibold text-slate-800">사람 확인</h2>
        <HumanChecks runId={runId} items={checks.human} />
      </div>
    </div>
  );
}
