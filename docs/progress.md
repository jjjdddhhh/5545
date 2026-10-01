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

## 단계 5. 검수와 수정 정책 (완료)

- `pipeline/checks.py`: C02~C12 검사 함수와 실행 전체 검수(run_checks). `app/rules/warning_terms.txt`(C10), `app/rules/hype_terms.txt`(C12)에 초안 표현을 채웠다.
- `pipeline/review.py`: DB에서 검수 입력을 모으고, C06·C07(자막 재분할), C09(일정 재배치), C10(주의사항 후보 추가)을 자동으로 고치고, 저장 정책(다시 요청해도 실패하면 경고)을 적용해 review_check에 저장한다. 사람 확인 H01~H03 행도 만든다.
- 생성 6단계가 review.evaluate를 쓰고, 사용자가 고칠 때마다 코드 검수를 다시 한다.
- API: `PATCH /api/scenes/{id}`, `POST /api/scenes/{id}/regenerate`(고친 필드는 고정값으로 넘기고 덮어쓰지 않음), `PUT /api/projects/{id}/scene-order`, `POST /api/projects/{id}/scenes`(장면 추가), `GET /api/runs/{id}/checks`, `POST /api/runs/{id}/checks/recheck`, `PUT /api/runs/{id}/human-checks/{H01~H03}`, `GET·PUT /api/prompts/{stage}`, `POST /api/prompts/{stage}/versions/{n}/activate`.
- 모든 수정은 revision에 남는다(장면 필드, 내레이션, 장면 순서, 매뉴얼 단계, 일정).
- 테스트 84개 통과.

확인 방법:

- 생성 후 http://localhost:8000/api/runs/{run_id}/checks 에서 항목별 결과와 통과율(summary.pass_rate)을 본다.
- `app/rules/`의 표현 목록을 고친 뒤 `POST /api/runs/{run_id}/checks/recheck`로 다시 검수해 본다.

## 단계 6. 화면 (완료)

- `frontend/`: Vite, React 19, TypeScript, TanStack Query, Tailwind v4, react-router-dom으로 화면 5개를 만들었다. 모든 문구는 한국어다.
  - `/projects` 프로젝트 목록(만들기, 검색, 최근 실행 상태), `/projects/:id/source` 자료 입력(원문과 정제본 비교, 문단 합치기·나누기·종류 바꾸기), `/projects/:id/settings` 조건 설정(고급 설정은 접힘, 장면 수·글자 수 미리보기), `/runs/:runId` 생성 진행(SSE, 단계별 상태, LLM 호출 기록, 실패 사유), `/projects/:id/workspace` 결과 작업공간.
  - 결과 작업공간: 제목과 "전체 다시 생성", "내보내기"(SRT, DOCX, CSV, ICS, JSON), 탭 다섯 개, 왼쪽 장면 목록(검수 상태 점, 드래그 순서 변경, 장면 추가), 가운데 편집 영역("이 장면만 다시 생성", "수정 저장"), 오른쪽 검수 패널(자동 검수, 사람 확인 체크박스).
- API 주소는 `frontend/.env`의 `VITE_API_BASE`(기본 http://localhost:8000)다. `npm run build`가 통과한다.
- 가짜 LLM을 붙인 실제 백엔드에서 Playwright로 전체 흐름(만들기, 원고, 조건, 생성, 편집, 재생성, 장면 추가와 순서 변경, 매뉴얼·일정 수정, 검수, 내보내기)을 확인했다.

확인 방법: backend에서 `uvicorn app.main:app --reload --port 8000`, frontend에서 `npm run dev`를 실행한 뒤 http://localhost:5173 을 연다.

## 단계 7. 수정 요청 에이전트 연결 (완료)

- `agent/repo.py`: edit_agent.py의 Repo 프로토콜을 SQLAlchemy로 구현했다. 현재 구성안·매뉴얼만 볼 수 있고, split_subtitles는 단계 3의 함수, check는 단계 5의 검수 함수(C04, C06, C08, C11, C12)를 쓴다.
- `agent/service.py`: 백그라운드 스레드 실행, 도구 호출마다 agent_action 저장과 SSE 알림, 제안 저장(내레이션은 내레이션 id로), 승인(필드 반영, revision, 내레이션이면 자막 재분할, 다시 검수)과 거절.
- API: `POST /api/projects/{id}/edit-requests`(202), `GET /api/edit-requests/{id}/events`(SSE), `GET /api/edit-requests/{id}/proposals`, `POST /api/proposals/{id}/accept`, `POST /api/proposals/{id}/reject`, 그리고 `GET /api/edit-requests/{id}`, `GET /api/projects/{id}/edit-requests`.
- 화면(`frontend/src/components/workspace/EditRequestPanel.tsx`, `hooks/useEditEvents.ts`): 결과 작업공간 아래에 수정 요청 입력창(예시 문장, Ctrl+Enter), 에이전트가 부르는 도구의 진행 표시(SSE), 제안별 전후 비교, 내레이션 제안의 자막 미리보기, 제안 검수 결과, 승인·거절(사유 입력) 버튼을 붙였다. 사용자가 고친 필드에 대한 제안과 내용이 바뀐 제안에는 경고를 띄운다. 제안의 대상을 누르면 그 장면으로 이동하고, 이전 요청을 골라 남은 제안을 처리할 수 있다.
- 가짜 모델을 붙인 백엔드와 브라우저(Playwright)로 요청, 도구 진행, 제안 승인과 거절, 대상 장면 이동을 확인했다.

확인 방법: 결과 작업공간 맨 아래 "수정 요청"에 "3번 장면을 초보자용으로 더 쉽게 바꿔 줘"를 입력하고 보낸다. 실제 모델(qwen3:8b)과 Ollama가 켜져 있어야 한다.

## 단계 8. 실제 모델 확인과 평가 도구 (완료, 실행은 사용자)

- `docs/eval/sample_drill.txt`: 합성 샘플 원고(전동드릴 안전교육, 1,475자, 제목·목록·표 포함).
- `scripts/smoke_ollama.py`: 실제 모델로 한 번 생성해 단계별 표를 출력한다. `--model`로 qwen3:8b와 exaone3.5:7.8b를 비교한다.
- `docs/eval/requests.json`: 평가 요청 20개 초안(설계서 13절 유형별 개수). 기대 결과는 사용자가 확정한다.
- `scripts/run_eval.py`: 도구 선택 정확도, 제안 통과율, 거절 정확도, 평균 도구 호출 수를 `docs/eval/report.md`로 낸다.
- `scripts/report_metrics.py`: 생성 시간, 검수 통과율, 사용자 수정 횟수, 에이전트 승인율을 DB에서 뽑는다.
- README.md에 설치부터 실행까지 정리했다.
- 테스트 97개 통과.

## 남은 단계

구현 단계는 모두 끝났다. 위의 "사용자가 직접 할 일"과 아래 목록을 진행한다.

## 사용자가 직접 할 일 (구현 이후)

1. 위의 "사용자가 직접 할 일(사용자 PC)"대로 MySQL DB와 `.env`를 준비하고 `python scripts\check_db.py`, `python scripts\seed_prompts.py`, `alembic stamp head`를 실행한다.
2. Ollama에서 모델을 받는다: `ollama pull qwen3:8b`, 비교용 `ollama pull exaone3.5:7.8b`.
3. 실제 모델 확인을 실행하고 출력 전체를 PROMPT.md의 "3. 실제 모델 확인" 프롬프트에 붙인다(GPU 이름과 VRAM도 적는다).
   - `python scripts\smoke_ollama.py --model qwen3:8b --save ..\docs\eval\smoke_qwen3.json`
   - `python scripts\smoke_ollama.py --model exaone3.5:7.8b --save ..\docs\eval\smoke_exaone.json`
4. 백엔드(`uvicorn app.main:app --reload --port 8000`)와 화면(`npm run dev`)을 켜고 http://localhost:5173 에서 샘플 원고(`docs/eval/sample_drill.txt`)로 전체 흐름을 직접 써 본다. 생성 결과의 사람 확인(H01~H03)을 체크한다.
5. `docs/eval/requests.json`의 기대 결과 20개를 읽고 고친 뒤 `expected_confirmed`를 true로 바꾼다. 그다음 `python scripts\run_eval.py --prepare`로 평가하고 PROMPT.md의 "6. 수정 요청 에이전트 평가"를 쓴다.
6. 호롱불 원고와 규칙을 받으면 PROMPT.md의 4번과 5번 프롬프트를 쓴다. 경고·과장 표현 목록(`backend/app/rules/`)은 초안이다.
7. 결과보고서 지표는 `python scripts\report_metrics.py --out ..\docs\eval\metrics.md`로 뽑는다.

## 사용자와 정한 것

- 사용자가 "+ 장면 추가"로 만든 장면에도 C02·C03 경고를 그대로 띄운다.
- 생성 진행 화면은 다시 연결해도 모든 단계의 걸린 시간을 보여 준다(snapshot에 단계별 시간을 더했다).

## 테스트 현황

- 백엔드: `TEST_DATABASE_URL`이 있으면 97개 모두 통과, 없으면 65개 통과와 32개 skip.
- 화면: `npm run build` 통과.

