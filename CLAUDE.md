# AI 콘텐츠 기획·제작 자동화 플랫폼 (프로젝트 안내)

교육 원고를 넣으면 구성안, 장면별 스토리보드, 내레이션·자막, 대상별 맞춤 매뉴얼과 수행 일정을 만들고, 사용자가 결과를 고쳐 쓰는 웹 프로토타입이다. 전체 설계는 `docs/design.md`에 있다. 이 파일은 구현 중에 반드시 지킬 결정과 명령어만 추린 것이다.

## 반드시 지킬 설계 결정

1. **생성은 워크플로, 수정은 에이전트다.** 콘텐츠 생성은 코드가 정한 7단계를 순서대로 실행한다(설계서 4절). 결과 수정만 LLM이 도구를 스스로 고르는 에이전트로 만든다(13절). 생성 부분을 "에이전트"나 "오케스트레이터"라고 부르지 않는다.
2. **LLM은 문장을 쓰고, 숫자와 규칙은 코드가 계산한다.** 장면 수, 장면별 글자 수 예산, 자막 분할과 타이밍, 일정 날짜 배치, 검수는 모두 코드로 한다.
3. **원고에는 정해진 형식이 없다고 가정한다.** `app/pipeline/text_cleaner.py`가 원고를 300자 안팎의 번호 붙은 문단으로 나눈다. 코드는 원고의 구조를 추측해 장면을 나누지 않는다. "제목 후보" 표시는 LLM에게 참고로만 넘긴다.
4. **모든 장면과 매뉴얼 단계는 근거 문단 번호를 가진다.** 원고에 없는 사실과 수치는 쓰지 않으며, 검수 C03과 C08이 이를 확인한다(10절).
5. **생성 단계의 LLM 호출은 `app/llm/llm_client.generate` 하나로만 한다.** 스키마 강제, 1회 재요청, 로그 기록이 여기에 들어 있다. 에이전트만 도구 호출을 위해 `llm_client.client`를 직접 쓴다.
6. **LLM은 로컬 Ollama다.** 기본 모델은 qwen3:8b이고, 모든 요청에 num_ctx를 명시하고, think는 끈다. GPU가 하나이므로 LLM 요청은 동시에 보내지 않고 순서대로 보낸다(12절).
7. **RAG는 넣지 않는다.** 원고 한 편이 컨텍스트에 들어가고, 필요한 원문은 문단 번호로 정확히 꺼내기 때문이다. 임베딩 모델이나 벡터 DB는 사용자가 요청할 때만 추가한다.
8. **에이전트에는 쓰기 도구가 없다.** 모든 수정은 change_proposal로만 남고 사용자가 승인해야 반영된다. 도구 호출은 요청당 최대 8회, 제안은 최대 5개다. 원고와 기존 결과는 `<source>` 태그로 감싸 넘긴다.
9. **사용자가 고친 필드는 재생성 때 덮어쓰지 않는다.** scene과 manual_step의 edited_fields로 관리하고, 모든 수정은 revision에 기록한다.
10. **테라럭스(식물 DB) 요구사항은 범위에서 뺐다.** 식물 관련 테이블, 화면, API는 만들지 않는다.
11. **Docker 없이 노트북의 localhost에서 실행한다.** DB는 PC에 설치된 MySQL 8.0.16 이상을 쓴다. 포트는 화면 5173, 백엔드 8000, MySQL 3306, Ollama 11434다.

## 기술 스택

- 화면: React, TypeScript, Vite, TanStack Query, Tailwind CSS
- 백엔드: FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, sse-starlette
- DB: MySQL 8 (스키마는 `db/schema.sql`, 테이블 21개)
- LLM: Ollama Python 라이브러리
- 파일 처리: python-docx, pypdf, icalendar (hwpx는 표준 라이브러리 zipfile로 읽는다)

## 목표 폴더 구조

```text
backend/
  app/
    main.py              FastAPI 앱, CORS(localhost:5173 허용), 라우터 등록
    config.py            .env 읽기
    db/                  session.py, models.py (schema.sql과 1:1로 맞춘다)
    api/                 projects, sources, settings, runs(SSE), scenes, manual, checks, export, prompts, edit_requests, proposals
    pipeline/            text_cleaner.py(완성), budget.py, outline.py, scene_detail.py, narration.py,
                         subtitles.py, manual.py, schedule.py, checks.py, runner.py
    llm/                 llm_client.py(완성), schemas.py(단계별 출력 Pydantic 모델), prompts/(템플릿 원문)
    agent/               edit_agent.py(완성), repo.py(Repo 프로토콜의 SQLAlchemy 구현)
    export/              srt.py, docx_export.py, csv_ics.py
  scripts/               check_db.py, seed_prompts.py, smoke_ollama.py, run_eval.py, report_metrics.py
  tests/                 pytest
frontend/                React 앱(5개 화면)
db/                      schema.sql, seed.sql
docs/                    design.md(설계서), decisions.md, progress.md, eval/(originals/는 저장소 제외)
```

## 명령어

```bash
# DB 만들기 (최초 1회). MySQL 버전이 8.0.16 이상인지 먼저 확인한다: SELECT VERSION();
mysql -u root -p < db/schema.sql
mysql -u root -p -e "CREATE USER 'content_ai'@'localhost' IDENTIFIED BY '비밀번호'; GRANT ALL ON content_ai.* TO 'content_ai'@'localhost';"
mysql -u root -p content_ai < db/seed.sql

# 모델 준비
ollama pull qwen3:8b
ollama list

# 백엔드 (backend 폴더에서, .env는 저장소 루트의 .env.example을 복사해 만든다)
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest

# 화면 (frontend 폴더에서)
npm install
npm run dev
```

## 작업 규칙

- 코드 주석, 문서, 사용자에게 보여 주는 설명은 한국어로 쓴다. 값을 정한 근거는 주석으로 남긴다.
- 사용자에게 보여 주는 설명과 문서는 화살표(→) 축약이나 끝맺음 없는 단편 문장 없이, 완결된 문장으로 쓴다.
- 코드는 "..."나 "이하 생략" 없이 그대로 실행되는 전체를 쓴다.
- 이미 테스트를 통과한 세 모듈(text_cleaner, llm_client, edit_agent)은 인터페이스를 유지한다. 바꿔야 하면 테스트도 함께 고친다.
- 테스트에서는 실제 Ollama를 부르지 않고 monkeypatch로 가짜 응답을 쓴다. 실제 모델 확인은 `scripts/smoke_ollama.py`로 따로 한다.
- 사용자의 PC는 Windows일 수 있다. 경로는 pathlib로 다루고, 파일은 인코딩(utf-8)을 명시해 연다.
- 설계서와 다르게 구현해야 하면 `docs/decisions.md`에 날짜, 무엇을, 왜를 한 줄로 남기고 진행한다. 단, DB 스키마 변경과 기능 삭제는 먼저 사용자에게 묻는다.
- 호롱불에서 받은 실제 원고와 결과물은 `docs/eval/originals/`에 두며, 이 폴더는 .gitignore에 들어 있어 저장소에 올라가지 않는다. 테스트에는 실제 원고 문장을 넣지 않고, 비슷한 모양의 합성 문장을 만들어 쓴다.
- 단계를 마칠 때마다 `docs/progress.md`에 끝난 단계, 남은 단계, 사용자가 확인할 것을 적는다. 새 대화에서는 이 파일과 `git log`를 먼저 읽고 이어서 작업한다.
