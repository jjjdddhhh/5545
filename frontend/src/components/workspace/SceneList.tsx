// SceneList.tsx : 결과 작업공간 왼쪽 칸의 장면 목록(와이어프레임 왼쪽 칸).
// 장면마다 "번호. 제목"과 검수 상태 점(통과 초록, 경고 주황, 실패 빨강, 검수 전 회색)을 보여 준다.
// 장면을 끌어 놓으면 순서를 바꾸고 PUT /api/projects/{id}/scene-order로 저장한다(설계서 5절 "편집" 칸).
// 끌어 놓기는 별도 라이브러리 없이 브라우저 기본 HTML5 drag and drop으로 만들었다. 목록이 한 줄짜리라 기본 기능으로 충분하다.
// 맨 아래 "+ 장면 추가"는 제목을 물은 뒤 POST /api/projects/{id}/scenes로 맨 뒤에 장면을 더한다.
import { useState, type DragEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addScene, qk, reorderScenes } from "../../api/endpoints";
import type { OutlineView, SceneOut } from "../../api/types";
import { formatSec } from "../../lib/labels";
import { ErrorBox, Spinner, StatusDot } from "../ui";

interface Props {
  projectId: number;
  runId: number | null;
  outline: OutlineView;
  selectedId: number | null;
  onSelect: (sceneId: number) => void;
}

export default function SceneList({ projectId, runId, outline, selectedId, onSelect }: Props) {
  const queryClient = useQueryClient();
  // 끌고 있는 장면 id와, 지금 마우스가 올라가 있는 장면 id. 놓을 자리를 선으로 보여 주는 데 쓴다.
  const [dragId, setDragId] = useState<number | null>(null);
  const [overId, setOverId] = useState<number | null>(null);

  /**
   * 순서 저장. 응답을 기다리지 않고 캐시의 장면 순서를 먼저 바꿔(낙관적 갱신) 끌어 놓은 결과가 바로 보이게 하고,
   * 실패하면 이전 순서로 되돌린다. 서버 응답(OutlineView 전체)이 오면 그 값으로 캐시를 바꾼다.
   * 순서만 바뀌고 검수 대상 내용은 그대로이므로 검수 쿼리는 무효화하지 않는다.
   */
  const reorder = useMutation({
    mutationFn: (ids: number[]) => reorderScenes(projectId, ids),
    onMutate: async (ids: number[]) => {
      await queryClient.cancelQueries({ queryKey: qk.outline(projectId) });
      const prev = queryClient.getQueryData<OutlineView>(qk.outline(projectId));
      if (prev) {
        const byId = new Map(prev.scenes.map((s) => [s.id, s]));
        // 시작 시각(start_sec)도 새 순서로 다시 더해 둔다. 서버 응답이 오면 어차피 서버 값으로 바뀐다.
        let start = 0;
        const scenes = ids.map((id, i) => {
          const s = byId.get(id)!;
          const out = { ...s, seq: i + 1, start_sec: start };
          start += s.duration_sec;
          return out;
        });
        queryClient.setQueryData<OutlineView>(qk.outline(projectId), { ...prev, scenes });
      }
      return { prev };
    },
    onError: (_err, _ids, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(qk.outline(projectId), ctx.prev);
    },
    onSuccess: (view) => queryClient.setQueryData(qk.outline(projectId), view),
  });

  /** 장면 추가. 새 장면은 검수 결과(장면 수 일치 C02 등)를 바꾸므로 구성안과 검수 쿼리를 함께 무효화한다. */
  const add = useMutation({
    mutationFn: (title: string) => addScene(projectId, title),
    onSuccess: (scene: SceneOut) => {
      queryClient.invalidateQueries({ queryKey: qk.outline(projectId) });
      if (runId) queryClient.invalidateQueries({ queryKey: qk.checks(runId) });
      onSelect(scene.id);
    },
  });

  function onAdd() {
    const title = window.prompt("새 장면의 제목을 입력해 주세요.");
    if (title && title.trim()) add.mutate(title.trim().slice(0, 200));
  }

  /** 놓았을 때: 끌던 장면을 놓은 장면 자리에 끼워 넣은 새 순서를 만들어 저장한다. 자리가 같으면 저장하지 않는다. */
  function onDrop(e: DragEvent, targetId: number) {
    e.preventDefault();
    const fromId = dragId ?? Number(e.dataTransfer.getData("text/plain"));
    setDragId(null);
    setOverId(null);
    if (!fromId || fromId === targetId) return;
    const ids = outline.scenes.map((s) => s.id);
    const from = ids.indexOf(fromId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ids.splice(from, 1);
    ids.splice(to, 0, fromId);
    reorder.mutate(ids);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold text-slate-800">장면 {outline.scenes.length}개</h2>
        <span className="text-xs text-slate-500">전체 {formatSec(outline.total_sec)}</span>
      </div>
      <p className="mb-2 px-1 text-[11px] text-slate-400">끌어서 순서를 바꿀 수 있습니다.</p>
      <ol className="flex-1 space-y-1 overflow-auto">
        {outline.scenes.map((s) => (
          <li
            key={s.id}
            draggable={!reorder.isPending}
            onDragStart={(e) => {
              setDragId(s.id);
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", String(s.id)); // Firefox는 데이터가 없으면 끌기를 시작하지 않는다
            }}
            onDragOver={(e) => {
              e.preventDefault(); // 기본 동작을 막아야 이 자리에 놓을 수 있다
              setOverId(s.id);
            }}
            onDragLeave={() => setOverId((o) => (o === s.id ? null : o))}
            onDrop={(e) => onDrop(e, s.id)}
            onDragEnd={() => {
              setDragId(null);
              setOverId(null);
            }}
            className={`rounded-md ${overId === s.id && dragId !== s.id ? "ring-2 ring-indigo-400" : ""} ${
              dragId === s.id ? "opacity-40" : ""
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(s.id)}
              className={`flex w-full cursor-grab items-center gap-2 rounded-md px-2 py-2 text-left text-sm active:cursor-grabbing ${
                selectedId === s.id ? "bg-indigo-50 font-medium text-indigo-900" : "hover:bg-slate-50"
              }`}
            >
              <span className="select-none text-slate-300" aria-hidden>
                ⋮⋮
              </span>
              <span className="min-w-0 flex-1 truncate">
                {s.seq}. {s.title}
              </span>
              <span className="text-[11px] text-slate-400">{s.duration_sec}초</span>
              <StatusDot status={s.check_status} />
            </button>
          </li>
        ))}
      </ol>
      {reorder.isPending && (
        <div className="mt-1 flex items-center gap-1 px-1 text-xs text-slate-500">
          <Spinner className="h-3 w-3" /> 순서를 저장하는 중입니다.
        </div>
      )}
      <ErrorBox error={reorder.error} className="mt-1" />
      <ErrorBox error={add.error} className="mt-1" />
      <button
        type="button"
        onClick={onAdd}
        disabled={add.isPending}
        className="mt-2 flex items-center justify-center gap-1 rounded-md border border-dashed border-slate-300 py-2 text-sm text-slate-600 hover:bg-slate-50"
      >
        {add.isPending && <Spinner className="h-3 w-3" />}+ 장면 추가
      </button>
    </div>
  );
}
