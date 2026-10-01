// Layout.tsx : 모든 화면의 공통 틀. 위쪽 머리줄(서비스 이름, 프로젝트 목록 링크, 상태 표시)과 본문 자리를 그린다.
// 상태 표시는 GET /api/health로 DB, Ollama, 모델 준비 여부를 보여 준다. 생성이 실패했을 때
// "Ollama가 꺼져 있었다" 같은 원인을 사용자가 바로 짐작할 수 있게 하려고 모든 화면 위에 둔다.
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "react-router-dom";
import { getHealth, qk } from "../api/endpoints";

/**
 * 상태 표시 하나(점과 이름). ok가 참이면 초록, 거짓이면 빨강, 아직 모르면 회색이다.
 * title에는 실패 원인(detail)을 넣어 마우스를 올리면 볼 수 있게 한다.
 */
function HealthPill({ label, ok, title }: { label: string; ok: boolean | undefined; title?: string }) {
  const color = ok === undefined ? "bg-slate-300" : ok ? "bg-emerald-500" : "bg-red-500";
  return (
    <span title={title} className="inline-flex items-center gap-1 text-xs text-slate-600">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

/**
 * 머리줄의 상태 표시 묶음.
 * 30초마다 다시 확인한다. 사용자가 작업 도중 Ollama를 켜거나 끌 수 있어서 한 번만 보면 부족하고,
 * 그보다 자주 보면 백엔드가 Ollama에 2초 대기 요청을 너무 자주 보내게 되어 30초로 정했다.
 */
function HealthIndicator() {
  const { data, isError } = useQuery({
    queryKey: qk.health,
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
  });
  if (isError) {
    return <HealthPill label="백엔드 연결 안 됨" ok={false} title="백엔드 서버(8000번 포트)가 켜져 있는지 확인해 주세요." />;
  }
  return (
    <div className="flex items-center gap-3">
      <HealthPill label="DB" ok={data?.db.ok} title={data?.db.ok ? data.db.version : data?.db.detail} />
      <HealthPill label="Ollama" ok={data?.ollama.ok} title={data?.ollama.detail} />
      <HealthPill
        label={`모델 ${data?.ollama.model ?? ""}`}
        ok={data ? Boolean(data.ollama.model_ready) : undefined}
        title={data && !data.ollama.model_ready ? `ollama pull ${data.ollama.model} 로 모델을 받아 주세요.` : undefined}
      />
    </div>
  );
}

/** 공통 틀. 라우터의 Outlet 자리에 각 화면이 들어간다. */
export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-12 max-w-[1600px] items-center justify-between gap-4 px-4">
          <Link to="/projects" className="text-sm font-bold text-slate-900">
            AI 콘텐츠 기획·제작
          </Link>
          <nav className="flex items-center gap-4">
            <Link to="/projects" className="text-sm text-slate-600 hover:text-slate-900">
              프로젝트 목록
            </Link>
            <HealthIndicator />
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5">
        <Outlet />
      </main>
    </div>
  );
}
