// useIdParam.ts : 주소의 숫자 매개변수(:id, :runId)를 숫자로 읽는 훅.
// 주소에 숫자가 아닌 값이 들어오면 NaN 대신 null을 돌려주어, 화면이 "잘못된 주소" 안내를 보여 줄 수 있게 한다.
import { useParams } from "react-router-dom";

/** name: 경로에 적은 매개변수 이름("id" 또는 "runId"). 양의 정수가 아니면 null이다. */
export function useIdParam(name: string): number | null {
  const params = useParams();
  const raw = params[name];
  const n = raw ? Number(raw) : NaN;
  return Number.isInteger(n) && n > 0 ? n : null;
}
