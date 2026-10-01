# 진행 상황

새 대화에서 이어서 작업할 때는 이 파일과 `git log --oneline -20`을 먼저 읽는다.

## 단계 0. 환경 점검과 저장소 준비 (완료)

| 항목 | 확인 결과 (클라우드 컨테이너) | 필요 조건 |
| --- | --- | --- |
| 운영체제 | Linux (Ubuntu 24.04) | Windows, macOS, Linux 모두 가능 |
| Python | 3.11.15 | 3.11 이상 |
| Node.js | 22.22.0 | 20 이상 |
| git | 2.43.0 | 아무 버전 |
| Ollama | 설치되어 있지 않음 (클라우드에는 GPU가 없어 설치하지 않았다) | 사용자 PC에 설치 |
| MySQL | 8.0.46 (검증용으로 컨테이너에 설치) | 8.0.16 이상 |

- 키트 상태를 첫 커밋으로 남겼고, `.env`는 `.gitignore`에 들어 있어 커밋되지 않는 것을 확인했다.
- backend 가상환경에 requirements.txt를 설치하고 pytest 16개가 모두 통과하는 것을 확인했다.
- `backend/scripts/check_db.py`를 만들었다. MySQL 버전이 8.0.16 이상인지, 테이블 21개가 있는지, app_user에 사용자가 있는지 확인한다.

## 사용자가 직접 할 일 (사용자 PC)

아래 명령어는 Windows PowerShell 기준이다. 저장소 루트 폴더에서 실행한다.

1. MySQL 버전을 확인한다. `mysql -u root -p -e "SELECT VERSION();"`의 결과가 8.0.16 이상이어야 한다.
2. DB와 사용자를 만든다. PowerShell은 `<` 리다이렉션을 지원하지 않으므로 `Get-Content`로 넘긴다.

```powershell
Get-Content db\schema.sql -Encoding utf8 | mysql -u root -p --default-character-set=utf8mb4
mysql -u root -p -e "CREATE USER 'content_ai'@'localhost' IDENTIFIED BY '원하는비밀번호'; GRANT ALL ON content_ai.* TO 'content_ai'@'localhost';"
Get-Content db\seed.sql -Encoding utf8 | mysql -u root -p --default-character-set=utf8mb4 content_ai
Copy-Item .env.example .env
notepad .env
```

3. `.env`의 `DATABASE_URL`에서 `비밀번호`를 위에서 정한 비밀번호로 바꾼다.
4. DB 준비를 확인한다.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\check_db.py
pytest
```

## 단계 1. 백엔드 뼈대와 원고 입력 (완료)

- `app/config.py`: 저장소 루트의 `.env`를 읽고, 분량·자막 기본값(장면당 30초, 분당 300자, 한 줄 16자, 최대 2줄, 허용 오차 ±15%)을 근거 주석과 함께 둔다.
- `app/db/session.py`, `app/db/models.py`: SQLAlchemy 2 모델 21개. `tests/test_models_schema.py`가 실제 MySQL에 적용한 schema.sql과 컬럼, NULL 허용, 외래키를 대조한다.
- Alembic: `0001_baseline` 리비전이 schema.sql을 그대로 실행한다. 이미 만든 DB는 `alembic stamp head`로 표시한다(README 참고).
- `app/main.py`: CORS(localhost:5173 허용), `GET /api/health`(DB와 Ollama 연결 여부).
- 프로젝트 API(만들기, 목록·검색, 상세), 원고 API(붙여넣기·파일 업로드와 비교 미리보기, hwp 안내 400, 문단 합치기·나누기 저장), 생성 조건 API(저장·조회).
- 테스트 22개 통과(DB 테스트 6개 포함).

확인 방법(backend 폴더에서 `uvicorn app.main:app --reload --port 8000` 실행 후):

- http://localhost:8000/docs 에서 API 문서를 보고 직접 호출해 볼 수 있다.
- http://localhost:8000/api/health 에서 `db.ok`가 true인지 확인한다. Ollama를 켜 두었다면 `ollama.ok`와 `model_ready`도 true다.

## 단계 2. 분량 계산, 구성안, 장면 상세 (완료)

- `pipeline/budget.py`: 장면 수(목표 분량을 장면당 30초로 나눠 반올림), 장면별 시간(정수로 고르게 나눔), 내레이션 글자 수 예산(공백 제외, 분당 300자)을 계산한다.
- `llm/schemas.py`: OutlineOut, SceneDetailOut, NarrationOut, ManualOut과 긴 원고 요약용 ChunkSummaryOut.
- `llm/prompts/`: 단계별 프롬프트 원문(system, user 파일). `llm/prompt_store.py`가 DB의 활성 버전을 먼저 쓰고, 없으면 파일을 쓴다.
- `scripts/seed_prompts.py`: 프롬프트와 Pydantic 출력 스키마를 prompt_template에 버전 1로 넣는다. 여러 번 실행해도 안전하다.
- `pipeline/llm_step.py`: 모든 생성 LLM 호출의 통로. 전역 잠금으로 한 번에 하나만 보내고, 시도마다 토큰 수, 걸린 시간, 잘림 위험을 기록한다.
- `pipeline/outline.py`, `pipeline/scene_detail.py`: 구성안 직후 C02·C03·C11, 장면 상세 직후 C11을 확인해 실패하면 그 단계만 1회 다시 요청한다. 긴 원고는 묶음별 요약 뒤 구성한다.
- `pipeline/runner.py`, `pipeline/events.py`: 실행별 스레드, 단계별 이벤트(SSE)와 DB 기록, 다시 연결할 때의 상태 복원, 서버 재시작 때 중단된 실행 정리.
- API: `POST /api/projects/{id}/runs`(202), `GET /api/runs/{id}/events`(SSE), `GET /api/runs/{id}`, `GET /api/runs/{id}/snapshot`, `GET /api/projects/{id}/outline`.
- 내레이션(5a), 매뉴얼(5b), 전체 검수(6)는 자리만 만들어 두었고 단계 3~5에서 채운다.
- 테스트 40개 통과(DB 없이 돌면 29개 통과, 11개 skip).

확인 방법:

- 처음 한 번 `python scripts\seed_prompts.py`를 실행해 프롬프트 버전 1을 넣는다.
- http://localhost:8000/docs 에서 프로젝트를 만들고 원고와 조건을 넣은 뒤 `POST /api/projects/{id}/runs`를 부른다. Ollama와 qwen3:8b가 준비되어 있어야 한다.
- 브라우저 주소창에 http://localhost:8000/api/runs/{run_id}/events 를 열면 진행 이벤트가 글자로 흘러나온다.

## 단계 3. 내레이션, 자막, SRT (완료)

- `pipeline/narration.py`: 장면별 내레이션을 글자 수 예산(공백 제외)에 맞춰 생성한다. 직후 C04(±15%)와 C11을 확인해 실패하면 그 장면만 1회 다시 요청한다. 괄호 지시문과 머리말은 코드로 지운다.
- `pipeline/subtitles.py`: 한 줄 16자, 최대 2줄, 단어 중간에서 끊지 않고, 문장마다 따로, 큐 길이와 두 줄 길이를 고르게 나눈다. 장면 시간을 글자 수에 비례해 배분하고 마지막 큐는 장면 끝에 정확히 맞춘다.
- `pipeline/persist.py`: 내레이션 저장과 자막 재분할, 수정 이력, edited_fields 기록을 한곳에 모았다.
- `export/srt.py`와 `GET /api/projects/{id}/export?format=srt`: 장면 시작 기준 시간을 영상 전체 기준으로 누적한다.
- `PATCH /api/narrations/{id}`: LLM 없이 자막을 즉시 다시 나누고 revision을 남기며, is_edited를 true로 바꾼다.
- 테스트 57개 통과.

확인 방법:

- 영상형이나 둘 다로 생성한 뒤 http://localhost:8000/api/projects/{id}/export?format=srt 를 열면 SRT 파일이 내려받아진다. 영상 편집기(예: 다빈치 리졸브, 프리미어)에 불러와 자막이 장면 시간에 맞는지 본다.

## 단계 4. 맞춤 매뉴얼, 주의사항, 일정 (완료)

- `pipeline/manual.py`: 대상과 난이도에 맞춘 매뉴얼 단계, 주의사항, 단계별 기간을 생성한다. 직후 C08(수치 대조), C03, C11을 확인해 실패하면 1회 다시 요청한다.
- `pipeline/schedule.py`: 일정을 시작일 기준 며칠째로 단계 순서대로 이어 붙인다. 기간과 주기는 1~365일로 맞춘다.
- `pipeline/checks.py`에 C08(숫자와 단위 대조)과 C09(일정 순서) 검사를 더했다.
- `export/csv_ics.py`(CSV, ICS), `export/docx_export.py`(스토리보드와 매뉴얼 DOCX), `export?format=json`.
- API: `GET /api/projects/{id}/manual`, `PATCH /api/manual-steps/{id}`, `PATCH /api/schedule-items/{id}`(기간을 바꾸면 뒤 일정이 다시 배치된다).
- 테스트 69개 통과.

확인 방법:

- 둘 다(both)로 생성한 뒤 아래 주소를 열어 파일을 받는다.
  - http://localhost:8000/api/projects/{id}/export?format=docx (Word로 열어 스토리보드 표와 매뉴얼 확인)
  - http://localhost:8000/api/projects/{id}/export?format=ics&start_date=2026-11-02 (구글 캘린더나 Outlook에 가져오기)
  - http://localhost:8000/api/projects/{id}/export?format=csv&start_date=2026-11-02 (엑셀에서 한글이 깨지지 않는지 확인)

## 남은 단계

단계 5부터 단계 8까지 남아 있다.
