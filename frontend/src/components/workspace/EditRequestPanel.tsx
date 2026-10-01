// EditRequestPanel.tsx : 결과 작업공간 아래쪽의 "수정 요청" 자리(설계서 5절, 13절).
// 단계 7에서 수정 요청 에이전트(자연어 요청 입력, 에이전트 도구 호출 진행, 변경 제안의 전후 비교와 승인·거절)를 여기에 붙인다.
// 지금은 자리만 잡아 둔 비활성 입력창이다. WorkspacePage는 projectId와 runId만 넘기므로,
// 단계 7에서는 이 파일의 내용만 바꾸면 작업공간 화면을 고치지 않고 기능을 넣을 수 있다.

/**
 * projectId: 수정 요청을 보낼 프로젝트(POST /api/projects/{id}/edit-requests).
 * runId: 현재 결과의 실행 번호. 제안을 승인한 뒤 검수 결과(qk.checks(runId))를 무효화할 때 쓴다.
 * 두 값은 단계 7에서 쓰므로 지금은 화면에 표시만 하지 않고 받아만 둔다.
 */
export default function EditRequestPanel({ projectId, runId }: { projectId: number; runId: number | null }) {
  return (
    <section
      className="rounded-lg border border-dashed border-slate-300 bg-white p-4"
      data-project-id={projectId}
      data-run-id={runId ?? ""}
    >
      <h2 className="mb-2 text-sm font-semibold text-slate-700">수정 요청</h2>
      <textarea
        disabled
        className="h-20 w-full resize-none rounded-md border border-slate-200 bg-slate-50 p-2 text-sm text-slate-500"
        placeholder="수정 요청 기능은 다음 단계에서 연결됩니다"
        aria-label="수정 요청 입력(준비 중)"
      />
      <p className="mt-1 text-xs text-slate-500">
        예: "3번 장면 내레이션을 더 짧게 줄여 줘"처럼 요청하면, 에이전트가 변경 제안을 만들고 사용자가 승인한 것만 반영됩니다.
      </p>
    </section>
  );
}
