// StepNav.tsx : 자료 입력, 조건 설정, 결과 작업공간 사이를 오가는 단계 표시줄.
// 설계서 5절의 화면 흐름(목록, 자료 입력, 조건 설정, 생성 진행, 결과)을 사용자가 지금 어디쯤인지 알 수 있게 보여 준다.
// 생성 진행 화면은 실행 id가 있어야 열 수 있으므로 링크로 넣지 않았다.
import { NavLink } from "react-router-dom";

/**
 * projectId: 링크를 만들 프로젝트 번호.
 * title: 단계 표시줄 왼쪽에 보여 줄 프로젝트 제목(없으면 생략).
 */
export default function StepNav({ projectId, title }: { projectId: number; title?: string }) {
  const steps = [
    { to: `/projects/${projectId}/source`, label: "1. 자료 입력" },
    { to: `/projects/${projectId}/settings`, label: "2. 조건 설정" },
    { to: `/projects/${projectId}/workspace`, label: "3. 결과 작업공간" },
  ];
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-lg font-semibold text-slate-900">{title ?? `프로젝트 ${projectId}`}</h1>
      <ol className="flex items-center gap-1 text-sm">
        {steps.map((s) => (
          <li key={s.to}>
            <NavLink
              to={s.to}
              className={({ isActive }) =>
                `rounded-md px-2.5 py-1 ${isActive ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-100"}`
              }
            >
              {s.label}
            </NavLink>
          </li>
        ))}
      </ol>
    </div>
  );
}
