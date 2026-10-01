// vite-env.d.ts : Vite가 주입하는 환경 변수(import.meta.env)의 타입 선언.
// VITE_API_BASE는 백엔드 주소다. .env에 없으면 api/client.ts가 http://localhost:8000 을 기본값으로 쓴다.
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
