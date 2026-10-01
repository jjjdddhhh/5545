// main.tsx : 화면 앱의 시작점. React를 #root에 붙이고, TanStack Query와 라우터를 감싼다.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

/**
 * TanStack Query 기본 설정.
 * - retry 1회: 일시적인 연결 끊김은 한 번 더 시도해 넘기되, 404(아직 없음)처럼 다시 해도 같은 결과인 요청을
 *   여러 번 반복해 화면이 오래 "불러오는 중"에 머물지 않게 한다. 404는 아래 함수에서 아예 다시 시도하지 않는다.
 * - refetchOnWindowFocus 끔: 사용자가 편집하던 중에 다른 창에 다녀오면 서버 값으로 덮어써져
 *   입력하던 내용이 사라지는 일을 막는다. 대신 수정 뒤에 바뀐 쿼리만 직접 무효화한다(설계서 5절).
 * - staleTime 10초: 같은 화면 안에서 탭을 오갈 때 같은 요청을 연달아 보내지 않게 한다.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, err) => {
        const status = (err as { status?: number }).status;
        if (status !== undefined && status >= 400 && status < 500) return false;
        return count < 1;
      },
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
