// ProjectsPage.tsx : 1번 화면 "프로젝트 목록"(설계서 5절).
// 프로젝트를 만들고 제목으로 검색한다. 각 줄에는 최근 실행 상태 배지가 있다.
// 줄을 누르면 GET /api/projects/{id}로 현재 결과가 있는지 보고, 구성안이나 매뉴얼이 있으면 결과 작업공간으로,
// 없으면 자료 입력 화면으로 보낸다. 목록 응답에는 결과 유무가 없어서 누를 때 한 번 더 묻는다.
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { createProject, getProject, listProjects, qk } from "../api/endpoints";
import { Card, ErrorBox, Loading, RunStatusBadge, Spinner, btn, inputCls } from "../components/ui";
import { formatDateTime } from "../lib/labels";

/**
 * 검색어 입력을 0.3초 늦게 반영하는 훅.
 * 글자를 칠 때마다 요청을 보내면 한글 조합 중간 글자("ㅈ", "저")로도 요청이 나가므로, 입력이 멈춘 뒤에만 보낸다.
 */
function useDebounced(value: string, delayMs = 300): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return v;
}

export default function ProjectsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  // 프로젝트를 누른 뒤 상세를 묻는 동안 그 줄에 회전 표시를 띄우려고 누른 id를 기억한다.
  const [opening, setOpening] = useState<number | null>(null);
  const [openError, setOpenError] = useState<unknown>(null);

  const projects = useQuery({ queryKey: qk.projects(q), queryFn: () => listProjects(q) });

  // 새 프로젝트를 만들면 목록 쿼리 전체를 무효화하고, 막 만든 프로젝트는 원고가 없으니 바로 자료 입력으로 보낸다.
  const create = useMutation({
    mutationFn: (t: string) => createProject(t),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: qk.projectsAll });
      setTitle("");
      navigate(`/projects/${p.id}/source`);
    },
  });

  function onCreate(e: FormEvent) {
    e.preventDefault();
    if (title.trim()) create.mutate(title.trim());
  }

  /** 프로젝트 줄을 눌렀을 때 갈 화면을 정한다. 결과(구성안이나 매뉴얼)가 있으면 작업공간, 없으면 자료 입력이다. */
  async function openProject(id: number) {
    setOpening(id);
    setOpenError(null);
    try {
      const detail = await queryClient.fetchQuery({ queryKey: qk.project(id), queryFn: () => getProject(id) });
      navigate(detail.outline || detail.manual ? `/projects/${id}/workspace` : `/projects/${id}/source`);
    } catch (err) {
      setOpenError(err);
    } finally {
      setOpening(null);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <h1 className="text-xl font-semibold">프로젝트 목록</h1>

      <Card title="새 프로젝트">
        <form onSubmit={onCreate} className="flex gap-2">
          <input
            className={inputCls}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="예: 신입 안전교육 · 전동드릴 사용법"
            maxLength={200}
            aria-label="새 프로젝트 제목"
          />
          <button type="submit" className={btn("primary")} disabled={!title.trim() || create.isPending}>
            {create.isPending && <Spinner />}만들기
          </button>
        </form>
        <ErrorBox error={create.error} className="mt-2" />
      </Card>

      <Card
        title="프로젝트"
        actions={
          <input
            className={`${inputCls} w-56`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="제목 검색"
            aria-label="제목 검색"
          />
        }
      >
        <ErrorBox error={openError} className="mb-2" />
        {projects.isLoading ? (
          <Loading />
        ) : projects.isError ? (
          <ErrorBox error={projects.error} />
        ) : projects.data && projects.data.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            {q ? "검색 결과가 없습니다." : "아직 프로젝트가 없습니다. 위에서 새 프로젝트를 만들어 주세요."}
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {projects.data?.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => openProject(p.id)}
                  className="flex w-full items-center justify-between gap-3 px-2 py-3 text-left hover:bg-slate-50"
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium text-slate-900">{p.title}</div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      최근 수정 {formatDateTime(p.updated_at)}
                      {p.latest_run?.error_message && (
                        <span className="ml-2 text-red-600">· {p.latest_run.error_message}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {opening === p.id && <Spinner />}
                    <span className="text-xs text-slate-500">최근 실행</span>
                    <RunStatusBadge status={p.latest_run?.status} />
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
