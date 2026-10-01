// SourceRefs.tsx : 근거 문단 번호(p3 등)를 누르면 원고의 그 문단을 펼쳐 보여 주는 컴포넌트.
// 설계서 결정 4 "모든 장면과 매뉴얼 단계는 근거 문단 번호를 가진다"에 따라, 사용자가 결과의 근거를 바로 확인할 수 있게 한다.
// 원문은 GET /api/projects/{id}/sources/latest(가장 최근 원고)에서 가져온다. 실행이 예전 원고를 썼어도
// 대개 번호가 같아서 프로토타입에서는 충분하다고 보고, 번호가 원고에 없으면 그렇게 안내한다.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getLatestSource, qk } from "../../api/endpoints";

/**
 * projectId: 원고를 가져올 프로젝트.
 * ids: 근거 문단 번호 목록. 비어 있으면 "근거 없음"을 보여 준다(검수 C03 실패에 해당).
 */
export default function SourceRefs({ projectId, ids }: { projectId: number; ids: string[] }) {
  const [open, setOpen] = useState<string | null>(null);
  // 같은 키로 캐시되므로 장면을 여러 개 그려도 원고 요청은 한 번만 나간다. 원고는 이 화면에서 바뀌지 않아 오래 캐시한다.
  const source = useQuery({
    queryKey: qk.sourceLatest(projectId),
    queryFn: () => getLatestSource(projectId),
    staleTime: 5 * 60_000,
    retry: false,
  });

  if (ids.length === 0) return <span className="text-xs text-red-600">근거 문단 없음</span>;
  const para = open ? source.data?.paragraphs.find((p) => p.id === open) : undefined;

  return (
    <span className="inline-flex flex-col gap-1">
      <span className="inline-flex flex-wrap gap-1">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setOpen(open === id ? null : id)}
            title="눌러서 원고의 이 문단을 봅니다."
            className={`rounded px-1.5 py-px font-mono text-xs ${
              open === id ? "bg-indigo-600 text-white" : "bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
            }`}
          >
            {id}
          </button>
        ))}
      </span>
      {open && (
        <span className="block max-w-prose rounded-md border border-indigo-100 bg-indigo-50/60 p-2 text-xs leading-relaxed text-slate-700">
          {source.isLoading
            ? "원고를 불러오는 중입니다."
            : para
              ? para.text
              : `현재 원고에 ${open} 문단이 없습니다. 생성 뒤에 원고를 고쳤을 수 있습니다.`}
        </span>
      )}
    </span>
  );
}
