# AI 콘텐츠 기획·제작 자동화 플랫폼 (웹 프로토타입)

교육 원고를 넣으면 구성안, 장면별 스토리보드, 내레이션·자막(SRT), 대상별 맞춤 매뉴얼과 수행 일정을 만들고, 사용자가 결과를 직접 고치거나 자연어로 수정을 요청해 고쳐 쓰는 웹 프로토타입이다.

- 설계서: `docs/design.md`
- 구현 규칙과 반드시 지킬 설계 결정: `CLAUDE.md`
- 진행 상황과 사용자가 할 일: `docs/progress.md`
- 설계서와 다르게 정한 것: `docs/decisions.md`

## 구성

| 계층 | 위치 | 내용 |
| --- | --- | --- |
| 화면 | `frontend/` | React, TypeScript, Vite, TanStack Query, Tailwind CSS. 화면 5개(프로젝트 목록, 자료 입력, 조건 설정, 생성 진행, 결과 작업공간) |
| API | `backend/app/api/` | FastAPI. 문서는 서버를 켠 뒤 http://localhost:8000/docs |
| 생성 워크플로 | `backend/app/pipeline/` | 코드가 순서를 정한 7단계(텍스트 정제, 분량 계산, 구성안, 장면 상세, 내레이션·자막 또는 매뉴얼·일정, 검수, 저장) |
| 수정 요청 에이전트 | `backend/app/agent/` | LLM이 조회·제안·검수 도구 7개를 골라 쓰고, 모든 수정은 사용자가 승인해야 반영된다 |
| LLM | `backend/app/llm/` | 로컬 Ollama(기본 qwen3:8b). 단계별 프롬프트 원문은 `llm/prompts/` |
| DB | `db/schema.sql` | MySQL 8.0.16 이상, 테이블 21개 |
| 평가 | `docs/eval/`, `backend/scripts/` | 샘플 원고, 테스트 요청 20개, 모델 확인·평가·지표 스크립트 |

포트는 화면 5173, 백엔드 8000, MySQL 3306, Ollama 11434다. Docker 없이 노트북 한 대에서 실행한다.

## 가장 쉬운 방법 (더블클릭 또는 VS Code)

Python 3.11 이상, Node.js 20 이상, MySQL 8.0.16 이상, Ollama를 설치한 뒤 다음처럼 합니다.

1. 처음 한 번 `setup.bat`을 더블클릭합니다. root 비밀번호를 물으면 MySQL을 설치할 때 정한 비밀번호를 넣습니다. 백엔드·화면 패키지, `.env`, DB와 사용자, 프롬프트를 모두 준비합니다. `mysql` 명령이 PATH에 없어도 되고, 이미 만든 DB나 사용자가 있으면 그대로 쓰며 비밀번호만 `.env`와 맞춥니다. 여러 번 실행해도 안전합니다.
2. 쓸 때마다 `start.bat`을 더블클릭합니다. 백엔드(8000)와 화면(5173)이 함께 켜지고 브라우저가 열립니다. 끌 때는 그 창에서 `Ctrl+C`를 누릅니다.

VS Code에서 저장소 폴더를 열었다면 `Ctrl+Shift+B`로 실행할 수 있습니다. 설치와 상태 확인, 테스트는 `Ctrl+Shift+P`를 누른 뒤 "Tasks: Run Task"에서 고릅니다. 터미널에서는 `python dev.py setup`, `python dev.py start`, `python dev.py check`로 같은 일을 합니다.

아래는 같은 과정을 명령어로 하나씩 하는 방법입니다.

## 설치부터 실행까지

아래 명령어는 Windows PowerShell 기준이다. macOS나 Linux에서는 가상환경 활성화를 `source .venv/bin/activate`로, 경로의 `\`를 `/`로 바꾸고, SQL 파일은 `mysql -u root -p < db/schema.sql`처럼 넣는다.

### 1. 필요한 프로그램

| 프로그램 | 버전 | 확인 명령 |
| --- | --- | --- |
| Python | 3.11 이상 | `python --version` |
| Node.js | 20 이상 | `node --version` |
| MySQL | 8.0.16 이상 | `mysql -u root -p -e "SELECT VERSION();"` |
| Ollama | 최신 | `ollama list` |
| git | 아무 버전 | `git --version` |

### 2. 모델 받기

```powershell
ollama pull qwen3:8b
ollama pull exaone3.5:7.8b   # 비교 실험용(선택). 비상업 라이선스라 시연과 비교까지만 쓴다
ollama list
```

### 3. DB 만들기 (최초 1회, 저장소 루트에서)

```powershell
Get-Content db\schema.sql -Encoding utf8 | mysql -u root -p --default-character-set=utf8mb4
mysql -u root -p -e "CREATE USER 'content_ai'@'localhost' IDENTIFIED BY '원하는비밀번호'; GRANT ALL ON content_ai.* TO 'content_ai'@'localhost';"
Get-Content db\seed.sql -Encoding utf8 | mysql -u root -p --default-character-set=utf8mb4 content_ai
Copy-Item .env.example .env
notepad .env    # DATABASE_URL의 "비밀번호"를 위에서 정한 비밀번호로 바꾼다
```

VRAM이 12GB 이상이면 `.env`의 `OLLAMA_NUM_CTX`를 16384로 올려도 된다(설계서 12절).

### 4. 백엔드 (backend 폴더에서)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\check_db.py        # MySQL 버전, 테이블 21개, 테스트 사용자 확인
python scripts\seed_prompts.py    # 단계별 프롬프트와 출력 스키마를 prompt_template에 버전 1로 넣는다
alembic stamp head                # schema.sql로 만든 DB를 Alembic 기준 리비전으로 표시한다
uvicorn app.main:app --reload --port 8000
```

http://localhost:8000/api/health 에서 `db.ok`, `ollama.ok`, `ollama.model_ready`가 모두 true인지 확인한다.

### 5. 화면 (새 터미널, frontend 폴더에서)

```powershell
cd frontend
Copy-Item .env.example .env       # VITE_API_BASE=http://localhost:8000
npm install
npm run dev
```

브라우저에서 http://localhost:5173 을 연다.

### 6. 사용 순서

1. 프로젝트 목록에서 프로젝트를 만든다.
2. 자료 입력에서 원고를 붙여넣거나 파일(txt, docx, pdf, hwpx)을 올리고, 원문과 정제본을 비교하며 문단을 합치거나 나눈다. hwp 파일은 한글 프로그램에서 hwpx, docx, pdf 중 하나로 저장해 올린다.
3. 조건 설정에서 유형, 대상, 난이도, 분량 또는 장면 수, 출력 언어를 고르고 생성을 시작한다.
4. 생성 진행 화면에서 단계별 상태를 본다. 화면을 닫아도 생성은 계속되고, 다시 열면 진행 위치가 복원된다.
5. 결과 작업공간에서 장면을 고치거나 "이 장면만 다시 생성"을 누르고, 수정 요청 입력창에 자연어로 요청한 뒤 제안을 승인하거나 거절한다. 검수 패널에서 자동 검수 결과를 보고 사람 확인 항목을 체크한다.
6. "내보내기"에서 SRT, DOCX, CSV, ICS, JSON을 내려받는다.

## 테스트

```powershell
cd backend
pytest
```

테스트는 실제 Ollama를 부르지 않고 가짜 응답을 쓴다. MySQL이 필요한 테스트는 환경변수 `TEST_DATABASE_URL`이 있을 때만 돌고, 없으면 건너뛴다. 테스트 DB는 운영 DB와 따로 만들어야 한다(테스트가 테이블을 지우고 다시 만든다).

```powershell
mysql -u root -p -e "CREATE DATABASE content_ai_test DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; GRANT ALL ON content_ai_test.* TO 'content_ai'@'localhost';"
$env:TEST_DATABASE_URL = "mysql+pymysql://content_ai:비밀번호@localhost:3306/content_ai_test"
pytest
```

화면은 `cd frontend` 뒤 `npm run build`로 타입 검사와 빌드를 확인한다.

## 실제 모델 확인과 평가 (backend 폴더에서)

```powershell
# 샘플 원고로 구성안부터 매뉴얼까지 한 번 생성해 단계별 JSON 성공, 재요청, 시간, 토큰, 잘림 위험을 표로 본다
python scripts\smoke_ollama.py --model qwen3:8b --save ..\docs\eval\smoke_qwen3.json
python scripts\smoke_ollama.py --model exaone3.5:7.8b --save ..\docs\eval\smoke_exaone.json

# 수정 요청 에이전트 평가(요청 20개). --prepare는 평가용 프로젝트 두 개(기본, 인젝션 원고)를 만들고 생성한다
python scripts\run_eval.py --prepare
# 이미 만든 평가용 프로젝트로 다시 평가할 때
python scripts\run_eval.py --project-id 3 --injected-project-id 4

# 결과보고서 지표(생성 시간, 검수 통과율, 사용자 수정 횟수, 에이전트 제안 승인율)
python scripts\report_metrics.py --out ..\docs\eval\metrics.md
```

`docs/eval/requests.json`의 기대 결과는 초안이며, 사용자가 확인한 뒤 `expected_confirmed`를 true로 바꾼다.

## 규칙과 설정을 바꾸는 곳

| 바꿀 것 | 위치 |
| --- | --- |
| 장면당 기본 시간, 분당 글자 수, 자막 줄 길이, 허용 오차 | `backend/app/config.py`(기본값). 프로젝트마다 조건 설정 화면의 고급 설정에서도 바꿀 수 있다 |
| 경고·금지 표현 목록(검수 C10) | `backend/app/rules/warning_terms.txt` |
| 과장·단정 표현 목록(검수 C12) | `backend/app/rules/hype_terms.txt` |
| 프롬프트 | `PUT /api/prompts/{stage}`로 새 버전을 저장한다(원문 버전 1은 `backend/app/llm/prompts/`) |
| 모델, 컨텍스트 길이 | 저장소 루트 `.env`의 `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` |

## DB 스키마 이력(Alembic)

DB 구조의 기준은 `db/schema.sql`이다. Alembic은 이 파일 전체를 기준 리비전 `0001_baseline` 하나로 등록해 두었다.

- 이미 `db/schema.sql`로 DB를 만들었다면 리비전을 실행하지 말고 표시만 한다. backend 폴더에서 `alembic stamp head`를 실행한다.
- 빈 DB에서 처음 만들 때는 `alembic upgrade head`가 `db/schema.sql`의 CREATE TABLE 문장을 차례로 실행한다.
- 현재 표시된 리비전은 `alembic current`로 확인한다.
- 이후 스키마를 바꿀 때는 `db/schema.sql`과 `backend/app/db/models.py`를 함께 고치고, `alembic revision -m "설명"`으로 새 리비전을 만든다.

## 문제 해결

| 증상 | 확인할 것 |
| --- | --- |
| `/api/health`의 db.ok가 false | `.env`의 DATABASE_URL 비밀번호, MySQL 서비스가 켜져 있는지, `python scripts\check_db.py` 출력 |
| ollama.ok가 false | Ollama가 켜져 있는지(작업 표시줄 아이콘 또는 `ollama serve`), `OLLAMA_HOST` 값 |
| model_ready가 false | `ollama pull qwen3:8b`를 했는지, `.env`의 `OLLAMA_MODEL`이 `ollama list`의 이름과 같은지 |
| 화면에서 요청이 막힘(CORS) | 화면을 http://localhost:5173 으로 열었는지, `.env`의 `FRONTEND_ORIGIN` |
| 생성이 "서버가 다시 시작되어 중단" | 생성 도중 백엔드를 다시 켜면 진행 중인 실행은 실패로 정리된다. 다시 생성한다 |
| 생성 로그에 잘림 위험 | 원고가 컨텍스트보다 길다. 자동으로 묶음별 요약 뒤 구성하지만, VRAM이 넉넉하면 `OLLAMA_NUM_CTX`를 올린다 |
