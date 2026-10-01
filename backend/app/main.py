# main.py : FastAPI 앱. CORS 설정, 라우터 등록, 상태 확인(/api/health)을 맡는다.
# 실행(backend 폴더에서): uvicorn app.main:app --reload --port 8000
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import config
from app.api import checks, edit_requests, export, manual, projects, prompts, runs, scenes, settings, sources
from app.db import session


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """앱이 켜질 때 한 번 실행한다. 서버가 꺼질 때 진행 중이던 생성 실행을 실패로 정리한다.
    DB에 연결하지 못해도 앱은 켜지게 한다(/api/health로 원인을 보여 주기 위해서다)."""
    from app.pipeline import runner
    try:
        db = session.SessionLocal()
        try:
            runner.recover_interrupted(db)
        finally:
            db.close()
    except Exception as exc:  # DB가 아직 준비되지 않은 경우
        print(f"[시작 점검] DB에 연결하지 못해 중단된 실행 정리를 건너뜁니다: {exc}")
    yield


app = FastAPI(title="AI 콘텐츠 기획·제작 자동화 플랫폼",
              description="원고로 구성안, 스토리보드, 내레이션·자막, 맞춤 매뉴얼과 일정을 만드는 프로토타입 API",
              lifespan=lifespan)

# 화면(5173)과 백엔드(8000)의 포트가 달라 브라우저가 다른 출처로 본다. 화면의 출처만 허용한다(설계서 11절).
# localhost와 127.0.0.1은 브라우저가 서로 다른 출처로 보므로 둘 다 넣는다.
_origins = {config.FRONTEND_ORIGIN, config.FRONTEND_ORIGIN.replace("localhost", "127.0.0.1")}
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_origins),
    allow_credentials=False,   # 로그인 쿠키가 없는 프로토타입이라 자격 증명은 주고받지 않는다
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],  # 내보내기 파일 이름을 화면이 읽을 수 있게 한다
)

for r in (projects.router, sources.router, settings.router, runs.router, scenes.router, manual.router, checks.router,
          prompts.router, edit_requests.router, export.router):
    app.include_router(r)

# Ollama 확인 대기 시간 2초: 같은 PC의 서버라 정상이면 수십 ms 안에 답한다. 꺼져 있을 때 화면이 오래 멈추지 않게 짧게 둔다.
OLLAMA_PING_TIMEOUT = 2.0


@app.get("/api/health", tags=["상태"])
def health():
    """DB와 Ollama에 연결되는지 돌려준다. 화면 첫 진입과 설치 확인에 쓴다.
    하나가 실패해도 500을 내지 않고 각각의 ok와 원인(detail)을 돌려준다."""
    out: dict = {"db": {"ok": False}, "ollama": {"ok": False, "model": config.OLLAMA_MODEL}}

    # ---------- DB ----------
    try:
        with session.get_engine().connect() as conn:
            out["db"] = {"ok": True, "version": conn.execute(text("SELECT VERSION()")).scalar_one()}
    except Exception as exc:  # 비밀번호 오류, 서버 꺼짐, DATABASE_URL 없음 등을 모두 detail로 넘긴다
        out["db"]["detail"] = str(exc)[:300]

    # ---------- Ollama ----------
    # ollama 라이브러리 대신 httpx로 /api/tags를 부르는 이유는 대기 시간을 짧게 정하기 위해서다.
    try:
        resp = httpx.get(f"{config.OLLAMA_HOST.rstrip('/')}/api/tags", timeout=OLLAMA_PING_TIMEOUT)
        resp.raise_for_status()
        names = [mdl.get("name", "") for mdl in resp.json().get("models", [])]
        out["ollama"].update({
            "ok": True,
            "models": names,
            # "qwen3:8b"처럼 태그까지 같은지 본다. 태그 없이 적었으면 ":latest"로 비교한다.
            "model_ready": any(n == config.OLLAMA_MODEL or n == f"{config.OLLAMA_MODEL}:latest" for n in names),
        })
    except Exception as exc:
        out["ollama"]["detail"] = f"Ollama({config.OLLAMA_HOST})에 연결하지 못했습니다: {exc}"[:300]
    return out
