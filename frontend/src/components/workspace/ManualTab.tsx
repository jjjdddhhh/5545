// ManualTab.tsx : 결과 작업공간의 "매뉴얼·일정" 탭.
// GET /api/projects/{id}/manual로 맞춤 매뉴얼(단계), 주의사항, 수행 일정을 받아 보여 주고, 단계와 일정을 그 자리에서 고친다.
// - 단계 수정: PATCH /api/manual-steps/{id} (제목, 설명, 팁)
// - 일정 수정: PATCH /api/schedule-items/{id} (제목, 기간, 반복 간격, 메모). 기간을 바꾸면 뒤 항목의 시작일을 서버 코드가 다시 배치한다.
// 두 API 모두 매뉴얼 전체(ManualView)를 돌려주므로 그 값으로 매뉴얼 캐시를 바로 바꾸고, 검수 쿼리만 무효화한다.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isStatus } from "../../api/client";
import { getManual, patchManualStep, patchScheduleItem, qk } from "../../api/endpoints";
import type { ChecksView, ManualStepOut, ManualStepPatch, ManualView, ScheduleItemOut, ScheduleItemPatch } from "../../api/types";
import { CAUTION_SOURCE_LABEL, DIFFICULTY_LABEL, SEVERITY_LABEL } from "../../lib/labels";
import { Badge, Card, EditedMark, ErrorBox, Loading, Notice, Spinner, StatusDot, btn, inputCls } from "../ui";
import { AutoCheckList } from "./CheckList";
import { checksForStep } from "./checkUtils";
import SourceRefs from "./SourceRefs";

/** 매뉴얼 수정 뒤 공통 처리를 돌려주는 훅. 응답(ManualView)으로 캐시를 바꾸고 검수만 무효화한다. */
function useManualUpdater(projectId: number, runId: number | null) {
  const queryClient = useQueryClient();
  return (view: ManualView) => {
    queryClient.setQueryData(qk.manual(projectId), view);
    if (runId) queryClient.invalidateQueries({ queryKey: qk.checks(runId) });
  };
}

/**
 * 매뉴얼 단계 하나. 평소에는 읽기 모양이고, "고치기"를 누르면 입력칸으로 바뀐다.
 * 저장할 때는 바뀐 필드만 보낸다. 서버가 바뀐 필드마다 수정 이력을 남기고 edited_fields에 기록한다.
 */
function StepItem({
  projectId,
  runId,
  step,
  checks,
}: {
  projectId: number;
  runId: number | null;
  step: ManualStepOut;
  checks: ChecksView | undefined;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(step.title);
  const [instruction, setInstruction] = useState(step.instruction);
  const [tip, setTip] = useState(step.tip ?? "");
  const onView = useManualUpdater(projectId, runId);

  const save = useMutation({
    mutationFn: (body: ManualStepPatch) => patchManualStep(step.id, body),
    onSuccess: (view) => {
      onView(view);
      setEditing(false);
    },
  });

  /** 편집을 시작할 때 지금 서버 값으로 입력칸을 채운다(다른 곳에서 바뀌었을 수 있으므로). */
  function startEdit() {
    setTitle(step.title);
    setInstruction(step.instruction);
    setTip(step.tip ?? "");
    setEditing(true);
  }

  function onSave() {
    if (!title.trim() || !instruction.trim()) {
      window.alert("단계 제목과 설명은 비워 둘 수 없습니다.");
      return;
    }
    const body: ManualStepPatch = {};
    if (title.trim() !== step.title) body.title = title.trim();
    if (instruction.trim() !== step.instruction) body.instruction = instruction.trim();
    if (tip.trim() !== (step.tip ?? "")) body.tip = tip.trim();
    if (Object.keys(body).length === 0) {
      setEditing(false);
      return;
    }
    save.mutate(body);
  }

  const edited = (f: string) => step.edited_fields.includes(f);
  const stepChecks = checks ? checksForStep(checks.auto, step.id) : [];

  return (
    <li className="rounded-md border border-slate-200 p-3">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-semibold text-white">
          {step.seq}
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          {editing ? (
            <>
              <input className={inputCls} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} aria-label="단계 제목" />
              <textarea className={inputCls} rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)} aria-label="단계 설명" />
              <input className={inputCls} value={tip} onChange={(e) => setTip(e.target.value)} placeholder="팁(선택)" aria-label="팁" />
              <ErrorBox error={save.error} />
              <div className="flex justify-end gap-2">
                <button type="button" className={btn("secondary", "sm")} onClick={() => setEditing(false)} disabled={save.isPending}>
                  취소
                </button>
                <button type="button" className={btn("primary", "sm")} onClick={onSave} disabled={save.isPending}>
                  {save.isPending && <Spinner className="h-3 w-3" />}수정 저장
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <h3 className="font-medium text-slate-900">
                  {step.title}
                  {edited("title") && <EditedMark />}
                </h3>
                <StatusDot status={step.check_status} />
                <button type="button" className={`${btn("ghost", "sm")} ml-auto`} onClick={startEdit}>
                  고치기
                </button>
              </div>
              <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
                {step.instruction}
                {edited("instruction") && <EditedMark />}
              </p>
              {step.tip && (
                <p className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
                  팁: {step.tip}
                  {edited("tip") && <EditedMark />}
                </p>
              )}
            </>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            근거 <SourceRefs projectId={projectId} ids={step.source_paragraphs} />
          </div>
          {stepChecks.some((c) => c.result !== "pass") && <AutoCheckList items={stepChecks.filter((c) => c.result !== "pass")} compact />}
        </div>
      </div>
    </li>
  );
}

/**
 * 일정 표의 한 줄. "고치기"를 누르면 제목, 기간(일), 반복 간격(일), 메모를 고칠 수 있다.
 * 시작일(며칠째)은 직접 고치지 않는다. 서버가 앞 항목의 기간을 보고 다시 배치하기 때문이다(검수 C09).
 */
function ScheduleRow({ projectId, runId, item }: { projectId: number; runId: number | null; item: ScheduleItemOut }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [duration, setDuration] = useState(String(item.duration_days));
  const [interval, setIntervalDays] = useState(item.interval_days?.toString() ?? "");
  const [note, setNote] = useState(item.note ?? "");
  const onView = useManualUpdater(projectId, runId);

  const save = useMutation({
    mutationFn: (body: ScheduleItemPatch) => patchScheduleItem(item.id, body),
    onSuccess: (view) => {
      onView(view);
      setEditing(false);
    },
  });

  function startEdit() {
    setTitle(item.title);
    setDuration(String(item.duration_days));
    setIntervalDays(item.interval_days?.toString() ?? "");
    setNote(item.note ?? "");
    setEditing(true);
  }

  /** 바뀐 값만 모아 보낸다. 반복 간격 칸을 비우면 0(반복 없음)으로 보낸다. 범위는 schemas.ScheduleItemPatch와 같다. */
  function onSave() {
    const d = Number(duration);
    if (!Number.isInteger(d) || d < 1 || d > 365) {
      window.alert("기간은 1일에서 365일 사이의 정수로 입력해 주세요.");
      return;
    }
    const iv = interval.trim() === "" ? 0 : Number(interval);
    if (!Number.isInteger(iv) || iv < 0 || iv > 365) {
      window.alert("반복 간격은 0일에서 365일 사이의 정수로 입력해 주세요. 비우면 반복하지 않습니다.");
      return;
    }
    if (!title.trim()) {
      window.alert("일정 제목은 비워 둘 수 없습니다.");
      return;
    }
    const body: ScheduleItemPatch = {};
    if (title.trim() !== item.title) body.title = title.trim();
    if (d !== item.duration_days) body.duration_days = d;
    if (iv !== (item.interval_days ?? 0)) body.interval_days = iv;
    if (note.trim() !== (item.note ?? "")) body.note = note.trim();
    if (Object.keys(body).length === 0) {
      setEditing(false);
      return;
    }
    save.mutate(body);
  }

  if (editing) {
    return (
      <>
        <tr className="border-t border-slate-100 bg-indigo-50/40 align-top">
          <td className="py-2 pr-2 text-slate-500">{item.seq}</td>
          <td className="py-2 pr-2">
            <input className={inputCls} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} aria-label="일정 제목" />
          </td>
          <td className="py-2 pr-2 text-slate-600">{item.start_offset_day + 1}일째</td>
          <td className="py-2 pr-2">
            <input className={`${inputCls} w-20`} type="number" min={1} max={365} value={duration} onChange={(e) => setDuration(e.target.value)} aria-label="기간(일)" />
          </td>
          <td className="py-2 pr-2">
            <input
              className={`${inputCls} w-20`}
              type="number"
              min={0}
              max={365}
              value={interval}
              placeholder="없음"
              onChange={(e) => setIntervalDays(e.target.value)}
              aria-label="반복 간격(일)"
            />
          </td>
          <td className="py-2 pr-2">
            <input className={inputCls} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} aria-label="메모" />
          </td>
          <td className="py-2 text-right">
            <div className="flex justify-end gap-1">
              <button type="button" className={btn("secondary", "sm")} onClick={() => setEditing(false)} disabled={save.isPending}>
                취소
              </button>
              <button type="button" className={btn("primary", "sm")} onClick={onSave} disabled={save.isPending}>
                {save.isPending && <Spinner className="h-3 w-3" />}저장
              </button>
            </div>
          </td>
        </tr>
        {save.error && (
          <tr>
            <td colSpan={7} className="pb-2">
              <ErrorBox error={save.error} />
            </td>
          </tr>
        )}
      </>
    );
  }

  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="py-2 pr-2 text-slate-500">{item.seq}</td>
      <td className="py-2 pr-2 font-medium text-slate-800">
        {item.title}
        {item.source === "user" && <EditedMark />}
      </td>
      {/* start_offset_day는 0부터 세므로 1을 더해 "1일째"부터 보여 준다. */}
      <td className="py-2 pr-2 text-slate-600">{item.start_offset_day + 1}일째</td>
      <td className="py-2 pr-2 text-slate-600">{item.duration_days}일</td>
      <td className="py-2 pr-2 text-slate-600">{item.interval_days ? `${item.interval_days}일마다` : "반복 없음"}</td>
      <td className="py-2 pr-2 text-slate-600">{item.note}</td>
      <td className="py-2 text-right">
        <button type="button" className={btn("ghost", "sm")} onClick={startEdit}>
          고치기
        </button>
      </td>
    </tr>
  );
}

const SEVERITY_TONE: Record<string, "slate" | "amber" | "red"> = { info: "slate", warning: "amber", danger: "red" };

export default function ManualTab({
  projectId,
  runId,
  checks,
}: {
  projectId: number;
  runId: number | null;
  checks: ChecksView | undefined;
}) {
  // 404는 "매뉴얼이 없음"(영상형으로만 생성)이라 오류 대신 안내를 보여 준다.
  const manual = useQuery({ queryKey: qk.manual(projectId), queryFn: () => getManual(projectId), retry: false });

  if (manual.isLoading) return <Loading />;
  if (isStatus(manual.error, 404))
    return <Notice>아직 생성된 매뉴얼이 없습니다. 조건 설정에서 유형을 매뉴얼형이나 둘 다로 바꿔 다시 생성해 주세요.</Notice>;
  if (manual.isError) return <ErrorBox error={manual.error} />;
  const m = manual.data!;

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <div className="space-y-4">
        <Card title="맞춤 매뉴얼">
          <h2 className="text-lg font-semibold text-slate-900">{m.manual.title}</h2>
          <p className="mt-1 text-xs text-slate-500">
            대상 {m.manual.audience} · 난이도 {DIFFICULTY_LABEL[m.manual.difficulty] ?? m.manual.difficulty}
          </p>
          {m.manual.intro && <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-700">{m.manual.intro}</p>}
          <ol className="mt-4 space-y-2">
            {m.steps.map((s) => (
              <StepItem key={s.id} projectId={projectId} runId={runId} step={s} checks={checks} />
            ))}
          </ol>
        </Card>
      </div>

      <div className="space-y-4">
        <Card title={`주의사항 ${m.cautions.length}개`}>
          {m.cautions.length === 0 ? (
            <p className="text-sm text-slate-500">주의사항이 없습니다.</p>
          ) : (
            <ul className="space-y-2">
              {m.cautions.map((c) => (
                <li key={c.id} className="flex items-start gap-2 text-sm">
                  <Badge tone={SEVERITY_TONE[c.severity] ?? "slate"}>{SEVERITY_LABEL[c.severity] ?? c.severity}</Badge>
                  <span className="flex-1 text-slate-800">{c.body}</span>
                  {/* rule은 검수 C10이 원고의 경고 문장에서 더한 것이다. 모델이 빠뜨린 경고를 코드가 채웠다는 뜻이다. */}
                  <Badge tone={c.source === "rule" ? "orange" : c.source === "user" ? "indigo" : "slate"}>
                    {CAUTION_SOURCE_LABEL[c.source] ?? c.source}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={`수행 일정 · 전체 ${m.total_days}일`}>
          {m.schedule.length === 0 ? (
            <p className="text-sm text-slate-500">일정이 없습니다.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-500">
                    <th className="w-8 py-1 font-medium">#</th>
                    <th className="py-1 font-medium">일정</th>
                    <th className="w-16 py-1 font-medium">시작</th>
                    <th className="w-24 py-1 font-medium">기간</th>
                    <th className="w-24 py-1 font-medium">반복</th>
                    <th className="py-1 font-medium">메모</th>
                    <th className="w-28 py-1" />
                  </tr>
                </thead>
                <tbody>
                  {m.schedule.map((it) => (
                    <ScheduleRow key={it.id} projectId={projectId} runId={runId} item={it} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-2 text-xs text-slate-500">
            기간을 바꾸면 뒤 일정의 시작일은 서버가 순서에 맞게 다시 배치합니다. 실제 날짜는 내보내기에서 시작일을 고르면 정해집니다.
          </p>
        </Card>
      </div>
    </div>
  );
}
