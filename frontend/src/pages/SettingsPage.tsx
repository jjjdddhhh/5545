// SettingsPage.tsx : 3번 화면 "조건 설정"(설계서 5절).
// 필수 다섯 항목(유형, 대상, 난이도, 분량 또는 장면 수, 출력 언어)과, 기본으로 접혀 있는 고급 설정(톤, 강조 키워드,
// 분당 글자 수, 장면당 기본 시간, 자막 한 줄 글자 수)을 받는다. 처음 쓰는 사람은 필수 항목만 채우고 바로 생성할 수 있다.
// "저장하고 생성 시작"은 설정 저장(PUT)과 생성 시작(POST /runs)을 차례로 부른 뒤 생성 진행 화면으로 이동한다.
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { isStatus } from "../api/client";
import { getProject, getSettings, qk, saveSettings, startRun } from "../api/endpoints";
import type { ContentType, Difficulty, SettingIn, SettingOut } from "../api/types";
import StepNav from "../components/StepNav";
import { Card, ErrorBox, Loading, Notice, Spinner, btn, inputCls } from "../components/ui";
import { useIdParam } from "../hooks/useIdParam";
import { MAX_DURATION_SEC, MAX_SCENES, computeBudget } from "../lib/budget";
import { CONTENT_TYPE_LABEL, DIFFICULTY_LABEL } from "../lib/labels";

/**
 * 입력 폼의 상태. 숫자 칸도 문자열로 들고 있다.
 * 숫자로 바로 바꾸면 사용자가 칸을 비웠을 때 0이 들어가 "비어 있음"과 "0"을 구분할 수 없기 때문이다.
 */
interface FormState {
  content_type: ContentType;
  audience: string;
  difficulty: Difficulty;
  target_duration_sec: string;
  scene_count: string;
  output_language: string;
  tone: string;
  keywords: string;
  narration_cpm: string;
  scene_default_sec: string;
  subtitle_max_chars: string;
}

/**
 * 처음 값. 고급 설정 기본값은 백엔드 config와 같다.
 * 분당 300자는 한국어 교육 내레이션의 보통 속도, 장면당 30초는 장면 하나에 학습 포인트 하나를 담기 좋은 길이,
 * 자막 한 줄 16자는 화면 아래 자막이 두 줄 안에 읽히는 길이로 정한 값이다(설계서 4절).
 */
const DEFAULT_FORM: FormState = {
  content_type: "both",
  audience: "",
  difficulty: "beginner",
  target_duration_sec: "",
  scene_count: "",
  output_language: "ko",
  tone: "",
  keywords: "",
  narration_cpm: "300",
  scene_default_sec: "30",
  subtitle_max_chars: "16",
};

/** 저장된 설정을 폼 상태로 바꾼다. 키워드 목록은 쉼표로 이어 한 칸에 보여 준다. */
function fromSetting(s: SettingOut): FormState {
  return {
    content_type: s.content_type,
    audience: s.audience,
    difficulty: s.difficulty,
    target_duration_sec: s.target_duration_sec?.toString() ?? "",
    scene_count: s.scene_count?.toString() ?? "",
    output_language: s.output_language,
    tone: s.tone ?? "",
    keywords: (s.keywords ?? []).join(", "),
    narration_cpm: String(s.narration_cpm),
    scene_default_sec: String(s.scene_default_sec),
    subtitle_max_chars: String(s.subtitle_max_chars),
  };
}

/** 빈 칸이면 null, 아니면 정수. 정수가 아니면 NaN을 돌려 검사에서 걸리게 한다. */
function toIntOrNull(v: string): number | null {
  if (!v.trim()) return null;
  const n = Number(v);
  return Number.isInteger(n) ? n : NaN;
}

/**
 * 폼 상태를 API 요청 본문으로 바꾸고, 서버에 보내기 전에 알아보기 쉬운 한국어로 먼저 검사한다.
 * 범위는 schemas.SettingIn과 같다. 서버도 같은 검사를 하지만, 화면에서 먼저 막으면 칸 옆에서 바로 고칠 수 있다.
 * 돌려주는 값: 문제가 없으면 { body }, 있으면 { error }.
 */
function toBody(f: FormState): { body?: SettingIn; error?: string } {
  const duration = toIntOrNull(f.target_duration_sec);
  const scenes = toIntOrNull(f.scene_count);
  const cpm = toIntOrNull(f.narration_cpm) ?? 300;
  const sceneSec = toIntOrNull(f.scene_default_sec) ?? 30;
  const subMax = toIntOrNull(f.subtitle_max_chars) ?? 16;
  if (!f.audience.trim()) return { error: "대상을 입력해 주세요. 예: 신입 사원" };
  if (duration === null && scenes === null) return { error: "목표 분량(초)과 장면 수 중 하나는 입력해야 합니다." };
  if (duration !== null && (Number.isNaN(duration) || duration < 10 || duration > MAX_DURATION_SEC))
    return { error: `목표 분량은 10초에서 ${MAX_DURATION_SEC}초 사이의 정수로 입력해 주세요.` };
  if (scenes !== null && (Number.isNaN(scenes) || scenes < 1 || scenes > MAX_SCENES))
    return { error: `장면 수는 1개에서 ${MAX_SCENES}개 사이로 입력해 주세요.` };
  if (Number.isNaN(cpm) || cpm < 100 || cpm > 600) return { error: "분당 글자 수는 100에서 600 사이로 입력해 주세요." };
  if (Number.isNaN(sceneSec) || sceneSec < 5 || sceneSec > 300)
    return { error: "장면당 기본 시간은 5초에서 300초 사이로 입력해 주세요." };
  if (Number.isNaN(subMax) || subMax < 8 || subMax > 40)
    return { error: "자막 한 줄 글자 수는 8에서 40 사이로 입력해 주세요." };
  // 쉼표(전각 쉼표 포함)로 나누고, 빈 값과 중복을 뺀다. 서버도 같은 정리를 하지만 개수 검사를 위해 먼저 한다.
  const keywords = Array.from(new Set(f.keywords.split(/[,，]/).map((k) => k.trim()).filter(Boolean)));
  if (keywords.length > 20) return { error: "강조 키워드는 20개까지 넣을 수 있습니다." };
  return {
    body: {
      content_type: f.content_type,
      audience: f.audience.trim(),
      difficulty: f.difficulty,
      target_duration_sec: duration,
      scene_count: scenes,
      output_language: f.output_language.trim() || "ko",
      tone: f.tone.trim() || null,
      keywords,
      narration_cpm: cpm,
      scene_default_sec: sceneSec,
      subtitle_max_chars: subMax,
    },
  };
}

/** 라벨과 입력칸을 한 줄로 묶는 틀. hint는 칸 아래 작은 설명이다. */
function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">
        {label}
        {required && <span className="ml-0.5 text-red-500">*</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

/** 여러 값 가운데 하나를 고르는 단추 묶음. 유형과 난이도처럼 선택지가 셋뿐인 항목에 쓴다. */
function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: Record<T, string>;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-slate-300 bg-white p-0.5">
      {(Object.keys(options) as T[]).map((k) => (
        <button
          key={k}
          type="button"
          role="radio"
          aria-checked={value === k}
          onClick={() => onChange(k)}
          className={`rounded px-3 py-1.5 text-sm ${value === k ? "bg-indigo-600 text-white" : "text-slate-700 hover:bg-slate-100"}`}
        >
          {options[k]}
        </button>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  const projectId = useIdParam("id");
  const pid = projectId ?? 0;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const project = useQuery({ queryKey: qk.project(pid), queryFn: () => getProject(pid), enabled: pid > 0 });
  // 404는 "아직 저장한 설정이 없음"이므로 기본값으로 시작한다.
  const saved = useQuery({ queryKey: qk.settings(pid), queryFn: () => getSettings(pid), enabled: pid > 0, retry: false });

  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  // 저장된 설정으로 폼을 한 번만 채운다. 그 뒤에 다시 채우면 사용자가 고치던 값이 사라진다.
  const [prefilled, setPrefilled] = useState(false);

  useEffect(() => {
    if (!prefilled && saved.data) {
      setForm(fromSetting(saved.data));
      setPrefilled(true);
    }
  }, [saved.data, prefilled]);

  /** 칸 하나를 바꾸는 함수. 바꾸면 이전 검사 오류 문구를 지운다. */
  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setFormError(null);
  }

  // 미리보기: 서버(budget.py)와 같은 규칙으로 장면 수와 장면당 글자 수를 계산한다. 숫자가 잘못되면 보여 주지 않는다.
  const preview = useMemo(() => {
    const d = toIntOrNull(form.target_duration_sec);
    const n = toIntOrNull(form.scene_count);
    const sec = toIntOrNull(form.scene_default_sec) ?? 30;
    const cpm = toIntOrNull(form.narration_cpm) ?? 300;
    if ([d, n, sec, cpm].some((v) => v !== null && Number.isNaN(v))) return null;
    return computeBudget(d, n, sec, cpm);
  }, [form.target_duration_sec, form.scene_count, form.scene_default_sec, form.narration_cpm]);

  /**
   * 저장하고 생성 시작. 두 요청을 차례로 보낸다.
   * 설정 저장이 실패하면 생성을 시작하지 않는다. 생성 시작이 실패하면(원고 없음 400, 이미 진행 중 409)
   * 서버 메시지를 그대로 보여 준다. 설정은 이미 저장되었으므로 다시 누르면 생성만 다시 시도된다.
   */
  const run = useMutation({
    mutationFn: async (body: SettingIn) => {
      const s = await saveSettings(pid, body);
      queryClient.setQueryData(qk.settings(pid), s);
      return startRun(pid);
    },
    onSuccess: ({ run_id }) => {
      queryClient.invalidateQueries({ queryKey: qk.project(pid) });
      queryClient.invalidateQueries({ queryKey: qk.projectsAll });
      navigate(`/runs/${run_id}`);
    },
  });

  /** 설정만 저장(생성은 하지 않음). 조건만 바꿔 두고 나중에 생성하려는 경우를 위해 둔다. */
  const saveOnly = useMutation({
    mutationFn: (body: SettingIn) => saveSettings(pid, body),
    onSuccess: (s) => queryClient.setQueryData(qk.settings(pid), s),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const { body, error } = toBody(form);
    if (error || !body) {
      setFormError(error ?? "입력을 확인해 주세요.");
      return;
    }
    run.mutate(body);
  }

  function onSaveOnly() {
    const { body, error } = toBody(form);
    if (error || !body) {
      setFormError(error ?? "입력을 확인해 주세요.");
      return;
    }
    saveOnly.mutate(body);
  }

  if (projectId === null) return <ErrorBox error="잘못된 주소입니다. 프로젝트 번호를 확인해 주세요." />;
  if (saved.isLoading) return <Loading />;

  const noSource = project.data && !project.data.source;

  return (
    <div>
      <StepNav projectId={pid} title={project.data?.title} />
      <form onSubmit={onSubmit} className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {saved.isError && !isStatus(saved.error, 404) && <ErrorBox error={saved.error} />}
          {noSource && (
            <Notice tone="warn">아직 원고가 없습니다. 자료 입력 화면에서 원고를 먼저 넣어야 생성할 수 있습니다.</Notice>
          )}

          <Card title="필수 설정">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="유형" required hint="영상형은 스토리보드와 내레이션·자막, 매뉴얼형은 맞춤 매뉴얼과 일정을 만듭니다.">
                <Segmented
                  label="유형"
                  value={form.content_type}
                  options={CONTENT_TYPE_LABEL as Record<ContentType, string>}
                  onChange={(v) => set("content_type", v)}
                />
              </Field>
              <Field label="난이도" required>
                <Segmented
                  label="난이도"
                  value={form.difficulty}
                  options={DIFFICULTY_LABEL as Record<Difficulty, string>}
                  onChange={(v) => set("difficulty", v)}
                />
              </Field>
              <Field label="대상" required hint="교육을 받는 사람입니다. 예: 신입 사원, 현장 관리자">
                <input
                  className={inputCls}
                  value={form.audience}
                  maxLength={100}
                  onChange={(e) => set("audience", e.target.value)}
                  placeholder="신입 사원"
                />
              </Field>
              <Field label="출력 언어" required hint="언어 코드입니다. 한국어는 ko, 영어는 en입니다.">
                <input
                  className={inputCls}
                  value={form.output_language}
                  maxLength={10}
                  onChange={(e) => set("output_language", e.target.value)}
                />
              </Field>
              <Field label="목표 분량(초)" hint="분량과 장면 수 중 하나는 꼭 입력합니다. 둘 다 넣으면 분량을 장면 수로 고르게 나눕니다.">
                <input
                  className={inputCls}
                  type="number"
                  min={10}
                  max={MAX_DURATION_SEC}
                  value={form.target_duration_sec}
                  onChange={(e) => set("target_duration_sec", e.target.value)}
                  placeholder="예: 150"
                />
              </Field>
              <Field label="장면 수" hint={`1개에서 ${MAX_SCENES}개까지 넣을 수 있습니다.`}>
                <input
                  className={inputCls}
                  type="number"
                  min={1}
                  max={MAX_SCENES}
                  value={form.scene_count}
                  onChange={(e) => set("scene_count", e.target.value)}
                  placeholder="비워 두면 분량으로 계산합니다"
                />
              </Field>
            </div>
          </Card>

          {/* 고급 설정은 기본으로 접어 둔다(설계서 5절). 처음 쓰는 사람이 필수 항목만 보고 바로 생성할 수 있게 하기 위해서다. */}
          <details className="group rounded-lg border border-slate-200 bg-white shadow-sm">
            <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-semibold text-slate-800">
              고급 설정 <span className="font-normal text-slate-500">(톤, 강조 키워드, 내레이션 속도, 자막 줄 길이)</span>
            </summary>
            <div className="grid gap-4 border-t border-slate-100 p-4 sm:grid-cols-2">
              <Field label="톤" hint="예: 친근하게, 단호하게">
                <input className={inputCls} value={form.tone} maxLength={50} onChange={(e) => set("tone", e.target.value)} />
              </Field>
              <Field label="강조 키워드" hint="쉼표로 구분합니다. 검수 C05가 결과에 들어갔는지 확인합니다.">
                <input
                  className={inputCls}
                  value={form.keywords}
                  onChange={(e) => set("keywords", e.target.value)}
                  placeholder="예: 보호장갑, 보안경"
                />
              </Field>
              <Field label="분당 글자 수" hint="내레이션 읽는 속도입니다. 기본 300자이며 100에서 600까지 넣을 수 있습니다.">
                <input
                  className={inputCls}
                  type="number"
                  min={100}
                  max={600}
                  value={form.narration_cpm}
                  onChange={(e) => set("narration_cpm", e.target.value)}
                />
              </Field>
              <Field label="장면당 기본 시간(초)" hint="장면 수를 비웠을 때 분량을 이 값으로 나눠 장면 수를 정합니다. 기본 30초입니다.">
                <input
                  className={inputCls}
                  type="number"
                  min={5}
                  max={300}
                  value={form.scene_default_sec}
                  onChange={(e) => set("scene_default_sec", e.target.value)}
                />
              </Field>
              <Field label="자막 한 줄 글자 수" hint="자막을 나누는 기준입니다. 기본 16자이며 8에서 40까지 넣을 수 있습니다.">
                <input
                  className={inputCls}
                  type="number"
                  min={8}
                  max={40}
                  value={form.subtitle_max_chars}
                  onChange={(e) => set("subtitle_max_chars", e.target.value)}
                />
              </Field>
            </div>
          </details>
        </div>

        {/* 오른쪽 칸: 미리보기와 실행 단추. 스크롤해도 따라오게 sticky로 둔다. */}
        <aside className="space-y-4 lg:sticky lg:top-16 lg:self-start">
          <Card title="미리보기">
            {preview ? (
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-600">장면 수</span>
                  <span className="font-semibold">{preview.sceneCount}개</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">전체 분량</span>
                  <span className="font-semibold">{preview.totalSec}초</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">장면당 시간</span>
                  <span className="font-semibold">
                    {Math.min(...preview.durations) === Math.max(...preview.durations)
                      ? `${preview.durations[0]}초`
                      : `${Math.min(...preview.durations)}~${Math.max(...preview.durations)}초`}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">장면당 내레이션 글자 수</span>
                  <span className="font-semibold">
                    {Math.min(...preview.charBudgets) === Math.max(...preview.charBudgets)
                      ? `${preview.charBudgets[0]}자`
                      : `${Math.min(...preview.charBudgets)}~${Math.max(...preview.charBudgets)}자`}
                  </span>
                </div>
                <p className="pt-1 text-xs text-slate-500">
                  서버와 같은 규칙으로 계산한 미리보기입니다. 실제 값은 생성할 때 서버가 다시 계산합니다.
                </p>
              </div>
            ) : (
              <p className="text-sm text-slate-500">목표 분량이나 장면 수를 입력하면 장면 수와 글자 수를 미리 보여 줍니다.</p>
            )}
          </Card>

          {formError && <ErrorBox error={formError} />}
          <ErrorBox error={run.error} />
          <ErrorBox error={saveOnly.error} />
          {saveOnly.isSuccess && !saveOnly.isPending && <Notice tone="success">설정을 저장했습니다.</Notice>}

          <div className="flex flex-col gap-2">
            <button type="submit" className={btn("primary")} disabled={run.isPending}>
              {run.isPending && <Spinner />}저장하고 생성 시작
            </button>
            <button type="button" className={btn("secondary")} onClick={onSaveOnly} disabled={saveOnly.isPending}>
              설정만 저장
            </button>
          </div>
        </aside>
      </form>
    </div>
  );
}
