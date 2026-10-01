// SourcePage.tsx : 2번 화면 "자료 입력"(설계서 5절, 4절 텍스트 변환 상세).
// 원고를 붙여넣거나 파일(txt, docx, pdf, hwpx)로 올리면, 서버(text_cleaner)가 300자 안팎의 번호 붙은 문단으로 나눈다.
// 이 화면은 원문과 정제본을 두 칸으로 나란히 보여 주고, 사용자가 문단을 합치거나 나누고 종류를 바꾼 뒤 저장하게 한다.
// 문단 나누기 규칙은 모두 서버에 있고, 화면은 사용자가 고친 문단 목록을 PUT /api/sources/{id}/paragraphs로 보내기만 한다.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { isStatus } from "../api/client";
import { getLatestSource, getProject, qk, saveParagraphs, uploadSource } from "../api/endpoints";
import type { ParagraphKind, SourceOut } from "../api/types";
import StepNav from "../components/StepNav";
import { Badge, Card, ErrorBox, Loading, Notice, Spinner, btn, inputCls } from "../components/ui";
import { useIdParam } from "../hooks/useIdParam";
import { KIND_LABEL } from "../lib/labels";

/** 편집 중인 문단 하나. key는 React 목록용 고유 값이라 합치거나 나눠도 다른 문단과 겹치지 않는다. */
interface DraftParagraph {
  key: string;
  kind: ParagraphKind;
  text: string;
}

/** 통계 키의 한국어 이름. text_cleaner.clean의 stats와 sources.paragraph_stats의 키를 모두 담았다. */
const STAT_LABEL: Record<string, string> = {
  paragraphs: "문단 수",
  headings: "제목 후보",
  tables: "표",
  clean_chars: "정제본 글자 수",
  raw_chars: "원문 글자 수",
  removed_lines: "지운 줄",
  joined_lines: "이어 붙인 줄",
};

const KIND_TONE: Record<ParagraphKind, "slate" | "indigo" | "sky"> = { body: "slate", heading: "indigo", table: "sky" };

// 새 문단 key를 만들 때 쓰는 일련번호. 화면이 살아 있는 동안만 겹치지 않으면 되므로 모듈 변수로 충분하다.
let keySeq = 0;
const newKey = () => `d${++keySeq}`;

/** 서버의 문단 목록을 편집용 목록으로 바꾼다. */
function toDraft(src: SourceOut): DraftParagraph[] {
  return src.paragraphs.map((p) => ({ key: newKey(), kind: p.kind, text: p.text }));
}

/**
 * 원고 입력 상자. 붙여넣기와 파일 올리기 두 가지 방법을 탭으로 고른다.
 * onUploaded: 서버가 돌려준 비교 미리보기(SourceOut)를 받아 화면에 반영하는 함수.
 */
function SourceInput({ projectId, onUploaded }: { projectId: number; onUploaded: (s: SourceOut) => void }) {
  const [mode, setMode] = useState<"paste" | "file">("paste");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);

  // 실패하면 서버의 한국어 안내가 그대로 보인다. hwp 파일이면 "hwpx, docx, pdf 중 하나로 저장해 올려 주세요"가 온다.
  const upload = useMutation({
    mutationFn: () => uploadSource(projectId, mode === "file" && file ? { file } : { text }),
    onSuccess: (s) => {
      onUploaded(s);
      setText("");
      setFile(null);
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    upload.mutate();
  }

  const canSubmit = mode === "paste" ? text.trim().length > 0 : file !== null;

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <div className="flex gap-1" role="tablist">
        {(["paste", "file"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            className={`rounded-md px-3 py-1.5 text-sm ${mode === m ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}
          >
            {m === "paste" ? "글 붙여넣기" : "파일 올리기"}
          </button>
        ))}
      </div>
      {mode === "paste" ? (
        <textarea
          className={`${inputCls} h-48 font-mono`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="교육 원고를 그대로 붙여넣어 주세요. 정해진 형식은 없어도 됩니다."
          aria-label="원고 붙여넣기"
        />
      ) : (
        <div className="space-y-1">
          {/* .hwp도 고를 수 있게 둔 이유는 서버가 변환 방법을 안내하는 400 메시지를 돌려주기 때문이다. */}
          <input
            type="file"
            accept=".txt,.md,.docx,.pdf,.hwpx,.hwp"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block text-sm"
            aria-label="원고 파일"
          />
          <p className="text-xs text-slate-500">txt, docx, pdf, hwpx 파일을 올릴 수 있습니다. 최대 20MB입니다.</p>
        </div>
      )}
      <ErrorBox error={upload.error} />
      <button type="submit" className={btn("primary")} disabled={!canSubmit || upload.isPending}>
        {upload.isPending && <Spinner />}정제하고 미리보기
      </button>
    </form>
  );
}

export default function SourcePage() {
  const projectId = useIdParam("id");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pid = projectId ?? 0;

  const project = useQuery({ queryKey: qk.project(pid), queryFn: () => getProject(pid), enabled: pid > 0 });
  // 404는 "아직 원고가 없음"이라 오류가 아니다. retry를 끄고 화면에서 따로 갈라 처리한다.
  const source = useQuery({
    queryKey: qk.sourceLatest(pid),
    queryFn: () => getLatestSource(pid),
    enabled: pid > 0,
    retry: false,
  });

  const [draft, setDraft] = useState<DraftParagraph[]>([]);
  const [dirty, setDirty] = useState(false);
  const [showInput, setShowInput] = useState(false);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  // 문단별 textarea 요소. "커서에서 나누기"를 누르면 그 문단 textarea의 selectionStart(커서 위치)를 읽어 둘로 자른다.
  // 단추를 눌러 포커스가 빠져도 textarea는 마지막 커서 위치를 selectionStart에 그대로 들고 있으므로,
  // 선택 이벤트를 따로 추적하지 않고 누르는 순간에 요소에서 바로 읽는다.
  const textareaRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});

  // 서버의 원고가 바뀌면(처음 불러옴, 새로 올림, 저장 후) 편집 목록을 서버 값으로 다시 채운다.
  useEffect(() => {
    if (source.data) {
      setDraft(toDraft(source.data));
      setDirty(false);
      textareaRefs.current = {};
    }
  }, [source.data]);

  const save = useMutation({
    mutationFn: () => saveParagraphs(source.data!.id, draft.map((d) => ({ kind: d.kind, text: d.text }))),
    onSuccess: (s) => {
      // 이미 생성에 쓴 원고였다면 서버가 새 원고 행을 만들어 id가 바뀐다. 이전 결과의 근거 번호를 지키기 위한 규칙이다.
      setSaveNotice(
        s.id !== source.data?.id
          ? `이 원고는 이전 생성에 쓰였기 때문에, 이전 결과의 근거 번호가 바뀌지 않도록 새 원고(id ${s.id})로 저장했습니다. 번호는 p1부터 다시 매겼습니다.`
          : "저장했습니다. 문단 번호는 p1부터 다시 매겼습니다.",
      );
      // 업로드 직후에만 정확한 경고 목록은 저장 응답에 없으므로, 이전 경고를 이어 붙여 둔다.
      queryClient.setQueryData(qk.sourceLatest(pid), { ...s, warnings: source.data?.warnings ?? [] });
      queryClient.invalidateQueries({ queryKey: qk.project(pid) });
    },
  });

  if (projectId === null) return <ErrorBox error="잘못된 주소입니다. 프로젝트 번호를 확인해 주세요." />;

  /** 새로 올린 원고를 캐시에 넣는다. 업로드 응답에만 정확한 통계와 경고가 있으므로 다시 조회하지 않고 그대로 쓴다. */
  function onUploaded(s: SourceOut) {
    queryClient.setQueryData(qk.sourceLatest(pid), s);
    queryClient.invalidateQueries({ queryKey: qk.project(pid) });
    setShowInput(false);
    setSaveNotice(null);
  }

  /** 편집 목록을 바꾸는 공통 함수. 바꿀 때마다 "저장 안 됨" 상태로 표시한다. */
  function update(next: DraftParagraph[]) {
    setDraft(next);
    setDirty(true);
    setSaveNotice(null);
  }

  /** i번째 문단과 바로 다음 문단을 하나로 합친다. 두 글 사이에는 띄어쓰기 하나를 넣는다. */
  function mergeNext(i: number) {
    if (i >= draft.length - 1) return;
    const a = draft[i];
    const b = draft[i + 1];
    const merged: DraftParagraph = { key: newKey(), kind: a.kind, text: `${a.text.trimEnd()} ${b.text.trimStart()}` };
    update([...draft.slice(0, i), merged, ...draft.slice(i + 2)]);
  }

  /**
   * i번째 문단을 커서 위치에서 둘로 나눈다. 커서가 맨 앞이나 맨 뒤면 빈 문단이 생기므로 나누지 않는다.
   * 뒤쪽 문단은 본문(body)으로 둔다. 제목 후보를 나누면 대개 뒤쪽은 본문이기 때문이다.
   */
  function splitAt(i: number) {
    const d = draft[i];
    const pos = textareaRefs.current[d.key]?.selectionStart ?? -1;
    const head = d.text.slice(0, pos).trim();
    const tail = d.text.slice(pos).trim();
    if (pos <= 0 || !head || !tail) {
      window.alert("나눌 위치에 커서를 두고 다시 눌러 주세요. 문단의 맨 앞이나 맨 뒤에서는 나눌 수 없습니다.");
      return;
    }
    update([
      ...draft.slice(0, i),
      { key: newKey(), kind: d.kind, text: head },
      { key: newKey(), kind: "body", text: tail },
      ...draft.slice(i + 1),
    ]);
  }

  /** i번째 문단을 지운다. 문단이 하나만 남으면 지우지 않는다(서버가 빈 목록을 거절한다). */
  function remove(i: number) {
    if (draft.length <= 1) return;
    update(draft.filter((_, j) => j !== i));
  }

  /** 다음 화면(조건 설정)으로 간다. 저장하지 않은 수정이 있으면 먼저 확인한다. */
  function goNext() {
    if (dirty && !window.confirm("저장하지 않은 문단 수정이 있습니다. 저장하지 않고 조건 설정으로 넘어갈까요?")) return;
    navigate(`/projects/${pid}/settings`);
  }

  const hasSource = Boolean(source.data);
  const noSource = isStatus(source.error, 404);

  return (
    <div>
      <StepNav projectId={pid} title={project.data?.title} />

      {source.isLoading ? (
        <Loading />
      ) : source.isError && !noSource ? (
        <ErrorBox error={source.error} />
      ) : null}

      {(noSource || showInput) && (
        <Card title={hasSource ? "원고 다시 넣기" : "원고 넣기"} className="mb-4">
          <SourceInput projectId={pid} onUploaded={onUploaded} />
        </Card>
      )}

      {source.data && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
              <Badge>{source.data.source_type === "file" ? `파일 · ${source.data.file_name ?? ""}` : "붙여넣은 글"}</Badge>
              {Object.entries(source.data.stats).map(([k, v]) => (
                <span key={k} className="rounded bg-white px-2 py-0.5 text-xs ring-1 ring-slate-200">
                  {STAT_LABEL[k] ?? k} {String(v)}
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              {!showInput && (
                <button type="button" className={btn("secondary")} onClick={() => setShowInput(true)}>
                  원고 다시 넣기
                </button>
              )}
              <button type="button" className={btn("primary")} onClick={goNext}>
                다음: 조건 설정
              </button>
            </div>
          </div>

          {source.data.warnings.length > 0 && (
            <Notice tone="warn">
              <ul className="list-disc pl-4">
                {source.data.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </Notice>
          )}

          {/* 원문과 정제본을 두 칸으로 나란히 둔다. 넓은 화면에서는 좌우, 좁은 화면에서는 위아래로 쌓인다. */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="원문">
              <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-700">
                {source.data.raw_text}
              </pre>
            </Card>

            <Card
              title={`정제본 · 문단 ${draft.length}개`}
              actions={
                <>
                  {dirty && <span className="text-xs text-amber-700">저장하지 않은 수정이 있습니다.</span>}
                  <button
                    type="button"
                    className={btn("secondary", "sm")}
                    disabled={!dirty || save.isPending}
                    onClick={() => source.data && setDraft(toDraft(source.data))}
                  >
                    되돌리기
                  </button>
                  <button
                    type="button"
                    className={btn("primary", "sm")}
                    disabled={!dirty || save.isPending}
                    onClick={() => save.mutate()}
                  >
                    {save.isPending && <Spinner className="h-3 w-3" />}문단 저장
                  </button>
                </>
              }
            >
              <ErrorBox error={save.error} className="mb-2" />
              {saveNotice && (
                <div className="mb-2">
                  <Notice tone="success">{saveNotice}</Notice>
                </div>
              )}
              <p className="mb-2 text-xs text-slate-500">
                문단 번호는 생성 결과의 근거 표시에 쓰입니다. 합치거나 나눈 뒤 저장하면 서버가 p1부터 번호를 다시 매깁니다.
                나누려면 글 안에서 나눌 자리를 누른 뒤 "커서에서 나누기"를 누르세요.
              </p>
              <ol className="max-h-[70vh] space-y-2 overflow-auto pr-1">
                {draft.map((d, i) => (
                  <li key={d.key} className="rounded-md border border-slate-200 p-2">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      {/* 저장 전에는 화면 순서대로 번호를 보여 준다. 저장하면 서버도 같은 순서로 번호를 매긴다. */}
                      <span className="font-mono text-xs font-semibold text-slate-500">p{i + 1}</span>
                      <Badge tone={KIND_TONE[d.kind]}>{KIND_LABEL[d.kind]}</Badge>
                      <select
                        className="rounded border border-slate-300 px-1 py-0.5 text-xs"
                        value={d.kind}
                        aria-label={`p${i + 1} 종류`}
                        onChange={(e) =>
                          update(draft.map((x, j) => (j === i ? { ...x, kind: e.target.value as ParagraphKind } : x)))
                        }
                      >
                        {(Object.keys(KIND_LABEL) as ParagraphKind[]).map((k) => (
                          <option key={k} value={k}>
                            {KIND_LABEL[k]}
                          </option>
                        ))}
                      </select>
                      <span className="ml-auto text-xs text-slate-400">{d.text.length}자</span>
                    </div>
                    <textarea
                      className={`${inputCls} min-h-[4.5rem] text-sm leading-relaxed`}
                      value={d.text}
                      rows={Math.min(8, Math.max(2, Math.ceil(d.text.length / 45)))}
                      aria-label={`p${i + 1} 내용`}
                      onChange={(e) => update(draft.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
                      ref={(el) => {
                        textareaRefs.current[d.key] = el;
                      }}
                    />
                    <div className="mt-1 flex gap-1">
                      <button
                        type="button"
                        className={btn("ghost", "sm")}
                        onClick={() => mergeNext(i)}
                        disabled={i >= draft.length - 1}
                      >
                        다음 문단과 합치기
                      </button>
                      <button type="button" className={btn("ghost", "sm")} onClick={() => splitAt(i)}>
                        커서에서 나누기
                      </button>
                      <button
                        type="button"
                        className={`${btn("ghost", "sm")} ml-auto text-red-600`}
                        onClick={() => remove(i)}
                        disabled={draft.length <= 1}
                      >
                        지우기
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
