// vite.config.ts : Vite 개발 서버와 빌드 설정.
// 포트를 5173으로 고정하는 이유는 백엔드 CORS가 http://localhost:5173 과 http://127.0.0.1:5173 만 허용하기 때문이다.
// strictPort를 켜 두면 5173이 이미 쓰이고 있을 때 다른 포트로 조용히 옮겨 가지 않고 오류를 내므로,
// "화면은 뜨는데 API가 CORS 오류로 막히는" 헷갈리는 상황을 미리 막을 수 있다.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
  },
});
