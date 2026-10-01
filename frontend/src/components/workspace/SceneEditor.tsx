// SceneEditor.tsx : 결과 작업공간 가운데 칸의 장면 편집 영역(와이어프레임 가운데 칸).
// "장면 N · 제목"과 장면 시간을 위에 보여 주고, 제목·학습 포인트·화면 설명·시각자료 제안·화면 텍스트·내레이션을 고친다.
// 내레이션 아래에는 글자 수와 예산(±15% 허용 범위), 자막 미리보기(시각 포함)를 보여 준다.
// 단추는 두 개다.
// - "이 장면만 다시 생성": POST /api/scenes/{id}/regenerate. LLM을 불러 수십 초 걸릴 수 있다. 사용자가 고친 필드는 서버가 지킨다.
// - "수정 저장"(강조): 바뀐 장면 필드만 PATCH /api/scenes/{id}로, 내레이션이 바뀌었으면 PATCH /api/narrations/{id}로 보낸다.
// 저장이나 재생성 뒤에는 구성안(qk.outline)과 검수(qk.checks)만 무효화한다. 매뉴얼은 장면과 관계없어 건드리지 않는다.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { patchNarration, patchScene, qk, regenerateScene } from "../../api/endpoints";
import type { RegenerateOut, SceneOut, ScenePatch } from "../../api/types";
import { countChars, toleranceRange } from "../../lib/budget";
import { SCENE_FIELD_LABEL, formatMs, formatSec } from "../../lib/labels";
import { EditedMark, ErrorBox, Notice, Spinner, btn, inputCls } from "../ui";
import SourceRefs from "./SourceRefs";

/** 편집할 수 있는 장면 필드. backend scenes.SCENE_FIELDS와 같은 다섯 개다. */
const FIELDS = ["title", "key_point", "screen_description", "visual_suggestion", "on_screen_text"] as const;
type Field = (typeof FIELDS)[number];

/** 편집 중인 값. 장면 필드 다섯 개와 내레이션 본문이다. null은 빈 문자열로 바꿔 입력칸에 넣는다. */
type Draft = Record<Field, string> & { narration: string };

/** 서버 장면을 편집용 값으로 바꾼다. */
function toDraft(s: SceneOut): Draft {
  return {
    title: s.title,
    key_point: s.key_point,
    screen_description: s.screen_description ?? "",
    visual_suggestion: s.visual_suggestion ?? "",
    on_screen_text: s.on_screen_text ?? "",
    narration: s.narration?.body ?? "",
  };
}

/** 라벨, "직접 수정함" 표시, 입력칸을 묶는 틀. */
function Row({ label, edited, children, extra }: { label: string; edited?: boolean; children: ReactNode; extra?: ReactNode }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-600">
          {label}
          {edited && <EditedMark />}
        </span>
        {extra}
      </div>
      {children}
    </div>
  );
}

interface Props {
  projectId: number;
  runId: number | null;
  scene: SceneOut;
  /** full은 스토리보드 탭(모든 필드), narration은 내레이션·자막 탭(내레이션과 자막 위주)이다. */
  mode?: "full" | "narration";
}

export default function SceneEditor({ projectId, runId, scene, mode = "full" }: Props) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => toDraft(scene));
  const [notice, setNotice] = useState<string | null>(null);
  // 바로 앞에 받은 서버 값. 서버 값이 바뀌었을 때 사용자가 손대지 않은 칸만 새 값으로 바꾸는 데 쓴다.
  const prevServer = useRef<Draft>(toDraft(scene));

  /**
   * 서버 장면이 바뀌면(저장, 재생성, 순서 변경 뒤 다시 조회) 편집 값을 맞춘다.
   * 모든 칸을 서버 값으로 덮으면 사용자가 다른 칸을 고치던 중에 그 내용이 사라지므로,
   * "편집 값이 이전 서버 값과 같은 칸", 즉 사용자가 손대지 않은 칸만 새 서버 값으로 바꾼다.
   */
  useEffect(() => {
    const next = toDraft(scene);
    const prev = prevServer.current;
    setDraft((d) => {
      const merged = { ...d };
      (Object.keys(next) as (keyof Draft)[]).forEach((k) => {
        if (d[k] === prev[k]) merged[k] = next[k];
      });
      return merged;
    });
    prevServer.current = next;
  }, [scene]);

  const server = toDraft(scene);
  const changedFields = FIELDS.filter((f) => draft[f] !== server[f]);
  const narrationChanged = scene.narration !== null && draft.narration !== server.narration;
  const dirty = changedFields.length > 0 || narrationChanged;

  /** 저장이나 재생성 뒤 공통 처리. 바뀐 쿼리(구성안, 검수)만 무효화한다. */
  function invalidate() {
    queryClient.invalidateQueries({ queryKey: qk.outline(projectId) });
    if (runId) queryClient.invalidateQueries({ queryKey: qk.checks(runId) });
  }

  /**
   * 수정 저장. 장면 필드와 내레이션은 API가 따로라서 차례로 부른다.
   * 장면 필드 PATCH가 실패하면 내레이션은 보내지 않는다. 오류가 나도 편집 값은 그대로 남아 다시 저장할 수 있다.
   */
  const save = useMutation({
    mutationFn: async () => {
      if (changedFields.length > 0) {
        const body: ScenePatch = {};
        // 서버(scenes.patch_scene)가 앞뒤 공백을 지우고 저장하므로 화면에서도 같은 값으로 보낸다.
        changedFields.forEach((f) => {
          body[f] = draft[f].trim();
        });
        await patchScene(scene.id, body);
      }
      if (narrationChanged && scene.narration) {
        await patchNarration(scene.narration.id, draft.narration.trim());
      }
    },
    onSuccess: () => {
      // 편집 값도 서버에 저장된 모양(앞뒤 공백 없음)으로 맞춘다. 맞추지 않으면 다시 조회한 뒤에도
      // 공백 차이 때문에 "저장하지 않은 수정"이 남은 것처럼 보인다.
      setDraft((d) => {
        const t = { ...d };
        changedFields.forEach((f) => {
          t[f] = d[f].trim();
        });
        if (narrationChanged) t.narration = d.narration.trim();
        return t;
      });
      setNotice("저장했습니다. 고친 필드는 이후 다시 생성해도 바뀌지 않습니다.");
      invalidate();
    },
    onError: () => invalidate(), // 장면은 저장되고 내레이션만 실패했을 수 있으므로 서버 값을 다시 받아 둔다
  });

  /** 이 장면만 다시 생성. 결과 안내에 실제로 다시 만든 부분과 사용자가 고쳐서 지킨 필드를 함께 알려 준다. */
  const regen = useMutation({
    mutationFn: () => regenerateScene(scene.id),
    onSuccess: (res: RegenerateOut) => {
      const done = res.regenerated.map((p) => SCENE_FIELD_LABEL[p] ?? p).join(", ") || "없음";
      const kept = res.kept.map((p) => SCENE_FIELD_LABEL[p] ?? p).join(", ");
      setNotice(`다시 생성했습니다. 다시 만든 부분: ${done}.${kept ? ` 직접 고친 ${kept}은(는) 그대로 두었습니다.` : ""}`);
      invalidate();
    },
  });

  function onRegenerate() {
    if (dirty && !window.confirm("저장하지 않은 수정이 있습니다. 저장하지 않은 내용은 다시 생성 결과로 바뀔 수 있습니다. 계속할까요?"))
      return;
    setNotice(null);
    regen.mutate();
  }

  function onSave() {
    if (!draft.title.trim()) {
      setNotice(null);
      window.alert("제목은 비워 둘 수 없습니다.");
      return;
    }
    if (!draft.key_point.trim()) {
      window.alert("학습 포인트는 비워 둘 수 없습니다.");
      return;
    }
    if (narrationChanged && !draft.narration.trim()) {
      window.alert("내레이션은 비워 둘 수 없습니다.");
      return;
    }
    setNotice(null);
    save.mutate();
  }

  const set = (k: keyof Draft, v: string) => {
    setDraft((d) => ({ ...d, [k]: v }));
    setNotice(null);
  };
  const edited = (f: string) => scene.edited_fields.includes(f);

  // 내레이션 글자 수와 예산. 공백을 뺀 글자 수로 세며, 예산의 ±15% 안이면 검수 C04를 통과한다.
  const chars = countChars(draft.narration);
  const range = toleranceRange(scene.char_budget);
  const inRange = chars >= range.min && chars <= range.max;
  const busy = save.isPending || regen.isPending;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900">
          장면 {scene.seq} · {scene.title}
        </h2>
        <span className="text-sm text-slate-500">
          {scene.duration_sec}초 · 시작 {formatSec(scene.start_sec)}
        </span>
      </div>

      {mode === "full" && (
        <>
          <Row label="제목" edited={edited("title")}>
            <input className={inputCls} aria-label="제목" value={draft.title} maxLength={200} onChange={(e) => set("title", e.target.value)} />
          </Row>
          <Row label="학습 포인트" edited={edited("key_point")}>
            <textarea
              className={inputCls}
              rows={2}
              maxLength={500}
              aria-label="학습 포인트"
              value={draft.key_point}
              onChange={(e) => set("key_point", e.target.value)}
            />
          </Row>
          <Row label="근거 문단">
            <SourceRefs projectId={projectId} ids={scene.source_paragraphs} />
          </Row>
          <Row label="화면 설명" edited={edited("screen_description")}>
            <textarea
              className={inputCls}
              rows={3}
              aria-label="화면 설명"
              value={draft.screen_description}
              onChange={(e) => set("screen_description", e.target.value)}
              placeholder="화면에 무엇이 어떻게 보이는지 적습니다."
            />
          </Row>
          <Row label="시각자료 제안" edited={edited("visual_suggestion")}>
            <textarea
              className={inputCls}
              rows={2}
              aria-label="시각자료 제안"
              value={draft.visual_suggestion}
              onChange={(e) => set("visual_suggestion", e.target.value)}
            />
          </Row>
          <Row label="화면 텍스트" edited={edited("on_screen_text")}>
            <input
              className={inputCls}
              maxLength={300}
              aria-label="화면 텍스트"
              value={draft.on_screen_text}
              onChange={(e) => set("on_screen_text", e.target.value)}
            />
          </Row>
        </>
      )}

      {scene.narration ? (
        <>
          <Row
            label="내레이션"
            edited={scene.narration.is_edited}
            extra={
              <span className={`text-xs ${inRange ? "text-emerald-700" : "text-orange-600"}`}>
                {chars}자 / 예산 {scene.char_budget}자 (허용 {range.min}~{range.max}자, 공백 제외)
              </span>
            }
          >
            <textarea
              className={`${inputCls} leading-relaxed`}
              rows={mode === "narration" ? 8 : 5}
              aria-label="내레이션"
              value={draft.narration}
              onChange={(e) => set("narration", e.target.value)}
            />
          </Row>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-600">자막 미리보기</span>
              {narrationChanged && (
                <span className="text-xs text-amber-700">내레이션을 고쳤습니다. 저장하면 자막을 코드가 다시 나눕니다.</span>
              )}
            </div>
            {scene.cues.length === 0 ? (
              <p className="text-xs text-slate-500">자막이 없습니다.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="w-8 py-1 font-medium">#</th>
                    <th className="w-36 py-1 font-medium">시간(장면 기준)</th>
                    <th className="w-24 py-1 font-medium">영상 전체 기준</th>
                    <th className="py-1 font-medium">자막</th>
                  </tr>
                </thead>
                <tbody>
                  {scene.cues.map((c) => (
                    <tr key={c.id} className="border-t border-slate-100 align-top">
                      <td className="py-1 text-slate-400">{c.seq}</td>
                      <td className="py-1 font-mono text-slate-600">
                        {formatMs(c.start_ms)} ~ {formatMs(c.end_ms)}
                      </td>
                      <td className="py-1 font-mono text-slate-400">{formatMs(scene.start_sec * 1000 + c.start_ms)}</td>
                      <td className="whitespace-pre-line py-1 text-slate-800">{c.body}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      ) : (
        <Notice>이 장면에는 내레이션이 없습니다. 매뉴얼형으로만 생성했거나 내레이션 생성에 실패한 장면입니다.</Notice>
      )}

      {notice && <Notice tone="success">{notice}</Notice>}
      <ErrorBox error={save.error} />
      <ErrorBox error={regen.error} />

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-3">
        {regen.isPending && (
          <span className="mr-auto text-xs text-slate-500">모델이 이 장면을 다시 쓰는 중입니다. 수십 초 걸릴 수 있습니다.</span>
        )}
        <button type="button" className={btn("secondary")} onClick={onRegenerate} disabled={busy}>
          {regen.isPending && <Spinner />}이 장면만 다시 생성
        </button>
        <button type="button" className={btn("primary")} onClick={onSave} disabled={!dirty || busy}>
          {save.isPending && <Spinner />}수정 저장
        </button>
      </div>
    </div>
  );
}
