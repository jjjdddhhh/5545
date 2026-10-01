// ExportMenu.tsx : 결과 작업공간 맨 위의 "내보내기" 단추와 펼침 메뉴.
// 설계서 5절 "파일은 서버가 만들고 화면은 내려받기만 한다"에 따라, 형식만 골라 GET /api/projects/{id}/export를 부른다.
// SRT(자막), DOCX(문서), CSV·ICS(일정), JSON(전체 결과) 다섯 가지이며, CSV와 ICS는 일정 시작일을 함께 보낸다.
import { useEffect, useRef, useState } from "react";
import { downloadFile } from "../../api/client";
import { ErrorBox, Spinner, btn, inputCls } from "../ui";

type Format = "srt" | "docx" | "csv" | "ics" | "json";

/** 형식별 설명. 메뉴에 이름과 함께 보여 준다. */
const FORMATS: { key: Format; label: string; desc: string }[] = [
  { key: "srt", label: "SRT", desc: "영상 자막 파일" },
  { key: "docx", label: "DOCX", desc: "스토리보드·매뉴얼 문서" },
  { key: "csv", label: "CSV", desc: "수행 일정 표" },
  { key: "ics", label: "ICS", desc: "캘린더 일정" },
  { key: "json", label: "JSON", desc: "전체 결과 데이터" },
];

/** 오늘 날짜를 "YYYY-MM-DD"로. 날짜 입력칸의 기본값이다. 브라우저의 현지 날짜를 쓰려고 toISOString(UTC) 대신 직접 만든다. */
function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function ExportMenu({ projectId }: { projectId: number }) {
  const [open, setOpen] = useState(false);
  const [startDate, setStartDate] = useState(today());
  // docx에 넣을 내용. 서버 기본값(all)은 스토리보드와 매뉴얼을 모두 넣는다.
  const [docKind, setDocKind] = useState<"all" | "storyboard" | "manual">("all");
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState<unknown>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  // 메뉴 바깥을 누르면 닫는다.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  /** 형식 하나를 내려받는다. 서버가 404(예: 일정 없음)를 주면 메뉴 안에 한국어 메시지를 보여 준다. */
  async function download(fmt: Format) {
    setBusy(fmt);
    setError(null);
    const params = new URLSearchParams({ format: fmt });
    if (fmt === "csv" || fmt === "ics") params.set("start_date", startDate);
    if (fmt === "docx") params.set("kind", docKind);
    try {
      await downloadFile(`/api/projects/${projectId}/export?${params.toString()}`, `export.${fmt}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="relative" ref={boxRef}>
      <button type="button" className={btn("primary")} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        내보내기 ▾
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-slate-200 bg-white p-3 shadow-lg">
          <ul className="space-y-1">
            {FORMATS.map((f) => (
              <li key={f.key}>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => download(f.key)}
                  className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-slate-50 disabled:opacity-50"
                >
                  <span>
                    <span className="font-semibold">{f.label}</span>
                    <span className="ml-2 text-xs text-slate-500">{f.desc}</span>
                  </span>
                  {busy === f.key && <Spinner className="h-3.5 w-3.5" />}
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-2 space-y-2 border-t border-slate-100 pt-2">
            <label className="block text-xs text-slate-600">
              일정 시작일 (CSV, ICS)
              <input type="date" className={`${inputCls} mt-0.5`} value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </label>
            <label className="block text-xs text-slate-600">
              문서에 넣을 내용 (DOCX)
              <select
                className={`${inputCls} mt-0.5`}
                value={docKind}
                onChange={(e) => setDocKind(e.target.value as "all" | "storyboard" | "manual")}
              >
                <option value="all">스토리보드와 매뉴얼</option>
                <option value="storyboard">스토리보드만</option>
                <option value="manual">매뉴얼만</option>
              </select>
            </label>
          </div>
          <ErrorBox error={error} className="mt-2" />
        </div>
      )}
    </div>
  );
}
