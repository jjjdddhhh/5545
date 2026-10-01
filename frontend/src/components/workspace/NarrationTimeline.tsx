// NarrationTimeline.tsx : 결과 작업공간의 "내레이션·자막" 탭에서 가운데 칸 아래에 붙는 전체 자막 표.
// 탭의 위쪽은 스토리보드와 같은 세 칸 배치에 장면 편집기를 내레이션 모드로 넣어 쓰고(WorkspacePage 참고),
// 이 컴포넌트는 모든 장면의 자막을 영상 전체 시각 순서로 이어 보여 준다. SRT로 내보내기 전에 흐름을 훑어보는 용도다.
import type { OutlineView } from "../../api/types";
import { formatMs } from "../../lib/labels";

interface Props {
  outline: OutlineView;
  selectedId: number | null;
  onSelect: (sceneId: number) => void;
}

export default function NarrationTimeline({ outline, selectedId, onSelect }: Props) {
  const rows = outline.scenes.flatMap((s) =>
    s.cues.map((c) => ({ scene: s, cue: c, abs: s.start_sec * 1000 + c.start_ms, absEnd: s.start_sec * 1000 + c.end_ms })),
  );
  if (rows.length === 0) return <p className="text-sm text-slate-500">자막이 없습니다. 영상형이나 둘 다로 생성했는지 확인해 주세요.</p>;
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-white">
          <tr className="text-left text-slate-500">
            <th className="w-16 py-1 font-medium">장면</th>
            <th className="w-40 py-1 font-medium">시간(영상 전체 기준)</th>
            <th className="py-1 font-medium">자막</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ scene, cue, abs, absEnd }) => (
            <tr
              key={cue.id}
              onClick={() => onSelect(scene.id)}
              className={`cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50 ${
                selectedId === scene.id ? "bg-indigo-50/60" : ""
              }`}
            >
              <td className="py-1 text-slate-500">장면 {scene.seq}</td>
              <td className="py-1 font-mono text-slate-600">
                {formatMs(abs)} ~ {formatMs(absEnd)}
              </td>
              <td className="whitespace-pre-line py-1 text-slate-800">{cue.body}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
