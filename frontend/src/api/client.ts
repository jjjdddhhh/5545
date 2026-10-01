// client.ts : 백엔드를 부르는 fetch 감싸개.
// 모든 API 호출은 이 파일의 request 함수를 거친다. 실패 응답이면 백엔드가 준 한국어 메시지(detail)를 담은
// ApiError를 던지므로, 화면은 error.message를 그대로 보여 주기만 하면 된다.

/**
 * 백엔드 주소. .env의 VITE_API_BASE를 쓰고, 없으면 기본 포트(8000)의 localhost를 쓴다.
 * 끝에 붙은 "/"는 지워서 `${API_BASE}/api/...`처럼 이어 붙여도 "//"가 생기지 않게 한다.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE || "http://localhost:8000").replace(/\/+$/, "");

/**
 * API 오류. status에는 HTTP 상태 코드를 담는다(네트워크 오류면 0).
 * 화면에서 "404면 아직 없음"처럼 상태 코드로 갈라 처리해야 하는 곳이 많아 따로 클래스를 만들었다.
 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** 오류가 특정 상태 코드의 ApiError인지 확인한다. 404를 "아직 없음"으로 다룰 때 쓴다. */
export function isStatus(err: unknown, status: number): boolean {
  return err instanceof ApiError && err.status === status;
}

/**
 * FastAPI 오류 본문에서 사람이 읽을 메시지를 뽑는다.
 * - HTTPException이면 {"detail": "한국어 메시지"} 모양이다.
 * - 입력 검사 실패(422)면 {"detail": [{"loc": [...], "msg": "..."}, ...]} 모양이므로 msg를 이어 붙인다.
 *   Pydantic 메시지 앞에 붙는 "Value error, " 같은 영어 머리말은 사용자에게 의미가 없어 지운다.
 */
function detailMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) => {
          if (d && typeof d === "object" && "msg" in d) {
            const msg = String((d as { msg: unknown }).msg).replace(/^Value error,\s*/, "");
            // loc의 마지막 값이 필드 이름이다. 어떤 칸이 잘못됐는지 알 수 있게 앞에 붙인다.
            const loc = (d as { loc?: unknown[] }).loc;
            const field = Array.isArray(loc) && loc.length > 1 ? String(loc[loc.length - 1]) : "";
            return field && field !== "body" ? `${field}: ${msg}` : msg;
          }
          return String(d);
        })
        .filter(Boolean);
      if (msgs.length) return msgs.join(" / ");
    }
  }
  return `요청을 처리하지 못했습니다 (HTTP ${status}).`;
}

/**
 * 공통 요청 함수.
 * - path는 "/api/..."처럼 슬래시로 시작하는 경로다.
 * - body가 FormData면 그대로 보내고(파일 업로드, 브라우저가 multipart 경계를 직접 붙인다),
 *   그 밖의 객체면 JSON으로 바꿔 보낸다.
 * - 성공 응답의 본문이 비어 있으면 undefined를 돌려준다.
 */
export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    // fetch는 서버가 꺼져 있거나 CORS로 막힐 때 응답 없이 TypeError를 던진다. 원인을 짐작할 수 있게 안내한다.
    throw new ApiError(0, `백엔드(${API_BASE})에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.`);
  }

  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text; // JSON이 아닌 응답(예: 프록시 오류 페이지)은 문자열 그대로 둔다
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, detailMessage(data, res.status));
  }
  return data as T;
}

/** 자주 쓰는 메서드의 짧은 이름. */
export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
};

/**
 * 파일 내려받기. 설계서 5절에 따라 파일은 서버가 만들고 화면은 받기만 한다.
 * window.location으로 바로 이동하지 않고 fetch로 받는 이유는, 서버가 404(예: "내보낼 일정이 없습니다")를 줄 때
 * 브라우저가 JSON 오류 페이지로 넘어가 버리지 않고 화면에 한국어 메시지를 보여 주기 위해서다.
 * 파일 이름은 Content-Disposition의 filename*(UTF-8, 한글 이름)을 먼저 쓰고, 없으면 filename을 쓴다.
 * 백엔드 CORS가 expose_headers에 Content-Disposition을 넣어 두었기 때문에 이 헤더를 읽을 수 있다.
 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`);
  } catch {
    throw new ApiError(0, `백엔드(${API_BASE})에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.`);
  }
  if (!res.ok) {
    let data: unknown = undefined;
    try {
      data = await res.json();
    } catch {
      data = undefined;
    }
    throw new ApiError(res.status, detailMessage(data, res.status));
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  let name = fallbackName;
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  if (star) name = decodeURIComponent(star[1]);
  else if (plain) name = plain[1];

  // 받은 내용을 임시 주소(blob URL)로 만들고, 보이지 않는 링크를 눌러 저장 창을 띄운 뒤 주소를 풀어 준다.
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 주소를 곧바로 풀면 일부 브라우저가 내려받기를 시작하기 전에 내용을 잃어 파일 이름이 "download"로 바뀌거나 실패한다.
  // 1분 뒤에 풀어도 메모리 부담은 내보내기 파일 하나 크기뿐이라 넉넉하게 기다린다.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
