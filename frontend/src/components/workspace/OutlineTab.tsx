// OutlineTab.tsx : 결과 작업공간의 "구성안" 탭.
// 구성안 제목, 요약, 학습 목표와 장면 표(번호, 제목, 학습 포인트, 근거 문단, 시간)를 한눈에 보여 준다.
// 장면 제목을 누르면 스토리보드 탭으로 넘어가 그 장면을 편집할 수 있다.
import type { OutlineView } from "../../api/types";
import { formatSec } from "../../lib/labels";
import { Card, EditedMark, StatusDot } from "../ui";
import SourceRefs from "./SourceRefs";

interface Props {
  projectId: number;
  outline: OutlineView;
  onOpenScene: (sceneId: number) => void;
}

export default function OutlineTab({ projectId, outline, onOpenScene }: Props) {
  const o = outline.outline;
  return (
    <div className="space-y-4">
      <Card title="구성안">
        <h2 className="text-lg font-semibold text-slate-900">{o.title}</h2>
        <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-700">{o.summary}</p>
        {o.learning_objectives.length > 0 && (
          <div className="mt-3">
            <h3 className="mb-1 text-xs font-semibold text-slate-600">학습 목표</h3>
            <ol className="list-decimal space-y-0.5 pl-5 text-sm text-slate-700">
              {o.learning_objectives.map((g, i) => (
                <li key={i}>{g}</li>
              ))}
            </ol>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          장면 {outline.scenes.length}개 · 전체 {formatSec(outline.total_sec)} ({outline.total_sec}초)
        </p>
      </Card>

      <Card title="장면 표">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="w-12 py-2 font-medium">번호</th>
                <th className="py-2 font-medium">제목</th>
                <th className="py-2 font-medium">학습 포인트</th>
                <th className="w-48 py-2 font-medium">근거 문단</th>
                <th className="w-20 py-2 text-right font-medium">시간</th>
                <th className="w-12 py-2 text-center font-medium">검수</th>
              </tr>
            </thead>
            <tbody>
              {outline.scenes.map((s) => (
                <tr key={s.id} className="border-b border-slate-100 align-top">
                  <td className="py-2 text-slate-500">{s.seq}</td>
                  <td className="py-2">
                    <button type="button" className="text-left font-medium text-indigo-700 hover:underline" onClick={() => onOpenScene(s.id)}>
                      {s.title}
                    </button>
                    {s.edited_fields.includes("title") && <EditedMark />}
                  </td>
                  <td className="py-2 text-slate-700">
                    {s.key_point}
                    {s.edited_fields.includes("key_point") && <EditedMark />}
                  </td>
                  <td className="py-2">
                    <SourceRefs projectId={projectId} ids={s.source_paragraphs} />
                  </td>
                  <td className="py-2 text-right text-slate-600">{s.duration_sec}초</td>
                  <td className="py-2 text-center">
                    <StatusDot status={s.check_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
