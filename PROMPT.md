# Claude Code 프롬프트 모음

이 폴더는 Claude Code로 구현을 시작하기 위한 시작 키트다. 설계서(`docs/design.md`), 구현 규칙(`CLAUDE.md`), DB 스키마(`db/schema.sql`), 테스트를 통과한 핵심 모듈 세 개(텍스트 변환, Ollama 호출, 수정 요청 에이전트)가 이미 들어 있다. 아래 프롬프트를 순서대로 Claude Code에 붙여 넣으면 된다.

## 시작하기 전에

1. 이 폴더의 압축을 풀어 원하는 위치(예: 문서 폴더 아래 content-ai-platform)에 둔다.
2. 터미널에서 이 폴더로 이동한 뒤 `claude`를 실행한다. Claude Code는 이 폴더의 `CLAUDE.md`를 자동으로 읽는다.
3. 아래 "1. 시작 프롬프트"를 그대로 붙여 넣는다. Claude Code가 단계마다 테스트와 커밋을 하고 보고한 뒤 다음 단계로 넘어간다. 도중에 MySQL 비밀번호나 Ollama 설치처럼 사람이 해야 할 일이 생기면 멈추고 알려 준다.
4. 대화가 길어져 끊기거나 다음 날 이어서 할 때는 "2. 이어서 하기"를 쓴다.
5. 3번부터 6번 프롬프트는 해당 시점이 되었을 때 쓴다.

## 1. 시작 프롬프트

```text
이 저장소는 "AI 콘텐츠 기획·제작 자동화 플랫폼" 웹 프로토타입의 시작 키트다. 설계서에 따라 끝까지 구현해 줘.

먼저 다음을 읽어라.
- CLAUDE.md (반드시 지킬 설계 결정 11가지와 작업 규칙)
- docs/design.md 전체 (설계서. 1~14절)
- db/schema.sql (테이블 21개. DB 구조의 기준이다)
- backend/app/pipeline/text_cleaner.py, backend/app/llm/llm_client.py, backend/app/agent/edit_agent.py와 backend/tests 아래 테스트 세 개

docs/design.md가 없으면 아무것도 만들지 말고 나에게 알려라.
읽은 뒤 이해한 내용을 10줄 이내로 요약하고, 내 답을 기다리지 말고 바로 단계 0부터 시작해라.

## 진행 방식
- 아래 단계를 순서대로 진행한다. 각 단계가 끝나면 (1) pytest 전체를 돌려 모두 통과시키고, (2) git에 한국어 메시지로 커밋하고, (3) docs/progress.md에 끝난 일, 남은 일, 내가 직접 확인할 것(브라우저 주소, 명령어)을 적고, (4) 같은 내용을 나에게 짧게 보고한 뒤 다음 단계로 넘어간다. 단계 사이에 "계속할까요?"라고 묻지 않는다.
- 다음 경우에만 멈추고 나에게 묻는다. 내가 직접 해야 하는 일(프로그램 설치, MySQL 계정과 비밀번호, .env 작성, 실제 모델 실행 확인)이 필요할 때, DB 스키마를 바꿔야 할 때, 설계서의 기능을 빼야 할 때다. 멈출 때는 내가 실행할 명령어를 내 운영체제에 맞게 그대로 복사할 수 있는 형태로 준다.
- 정보가 없어 판단이 필요한 경우에는 합리적으로 가정하고, 그 가정을 docs/decisions.md에 날짜, 무엇을, 왜를 한 줄로 남긴 뒤 진행한다.
- 이미 테스트를 통과한 세 모듈의 인터페이스는 유지한다. 테스트에서는 실제 Ollama를 부르지 않고 monkeypatch로 가짜 응답을 쓴다.
- MySQL이 필요한 테스트는 환경변수 TEST_DATABASE_URL이 있을 때만 돌고, 없으면 skip한다. 분량 계산, 자막 분할, 일정 배치, 검수 같은 순수 로직은 DB 없이 테스트한다.
- 코드는 "..."나 "이하 생략" 없이 전체를 쓰고, 값을 정한 근거는 주석으로 남긴다. 설명과 문서는 화살표(→) 축약 없이 완결된 문장으로 쓴다.
- 내 PC는 Windows일 수 있다. 셸 스크립트 대신 Python 스크립트를 쓰고, 경로는 pathlib로, 파일은 encoding="utf-8"로 연다.

## 단계 0. 환경 점검과 저장소 준비
- 운영체제, Python(3.11 이상), Node.js(20 이상), git, `ollama list` 결과를 확인해 표로 보고한다. 없는 것이 있으면 설치 방법을 알려 주고 멈춘다.
- git 저장소가 아니면 git init을 하고 키트 상태를 첫 커밋으로 남긴다. .env가 커밋되지 않는지 확인한다.
- backend에 가상환경을 만들고 requirements.txt를 설치한 뒤 pytest를 돌려 16개가 통과하는지 확인한다.
- MySQL은 내가 직접 준비한다. CLAUDE.md의 명령어로 DB와 content_ai 사용자를 만들고 seed.sql을 넣으라고 안내하고, 저장소 루트의 .env.example을 .env로 복사해 비밀번호를 채우라고 한 뒤 멈춘다. 내가 끝났다고 하면 backend/scripts/check_db.py를 만들어 SELECT VERSION()이 8.0.16 이상인지와 테이블이 21개인지 확인한다.

## 단계 1. 백엔드 뼈대와 원고 입력
- app/config.py: 저장소 루트의 .env를 pathlib로 찾아 읽는다(python-dotenv). 분량과 자막 기본값(장면당 30초, 분당 300자, 한 줄 16자, 최대 2줄, 내레이션 허용 오차 ±15%)을 근거 주석과 함께 여기에 둔다.
- app/db/session.py, app/db/models.py: SQLAlchemy 2 모델을 db/schema.sql과 1:1로 맞춘다. schema.sql이 기준이다. Alembic은 현재 schema.sql을 기준 리비전 하나로 초기화하고 `alembic stamp head`로 표시하는 방법을 README에 적는다.
- app/main.py: CORS로 FRONTEND_ORIGIN(localhost:5173)을 허용하고, GET /api/health에서 DB 연결과 Ollama 연결 여부를 돌려준다.
- 설계서 6절의 프로젝트, 원고, 설정 API를 만든다. POST /api/projects/{id}/sources는 붙여넣은 글과 파일을 모두 받고 text_cleaner로 정제해 원문, 정제본, 문단 목록을 저장하고 비교 미리보기를 돌려준다. PUT /api/sources/{id}/paragraphs는 문단을 합치거나 나눈 결과를 저장하고 번호를 다시 매긴다. hwp 파일이면 hwpx로 저장해 달라는 안내를 400 오류로 돌려준다.

## 단계 2. 분량 계산, 구성안, 장면 상세
- pipeline/budget.py: 설계서 4절 규칙대로 장면 수와 장면별 시간, 내레이션 글자 수 예산을 계산한다.
- llm/schemas.py: 설계서 9절의 단계별 출력 JSON 스키마를 Pydantic 모델로 만든다. llm/prompts/ 아래에 단계별 프롬프트 원문을 두고, 원고는 text_cleaner.to_prompt 결과(<source> 태그)로 넘긴다. scripts/seed_prompts.py는 모델의 JSON 스키마와 프롬프트를 prompt_template에 버전 1로 넣는다.
- pipeline/outline.py, pipeline/scene_detail.py: 모든 LLM 호출은 llm_client.generate로만 한다. 장면 상세는 장면마다 따로 호출한다.
- pipeline/runner.py: generation_run을 만들고 7단계를 순서대로 실행한다. LLM 호출마다 llm_client가 돌려준 로그(토큰 수, 걸린 시간, 잘림 위험)를 agent_step_log에 저장한다. GPU가 하나이므로 LLM 호출은 전역 잠금으로 한 번에 하나만 보낸다. 동기 Ollama 클라이언트는 별도 스레드에서 돌리고, 진행 이벤트는 실행별 큐로 SSE에 넘기면서 DB에도 남겨 다시 연결해도 상태를 알 수 있게 한다.
- API: POST /api/projects/{id}/runs(202와 run_id), GET /api/runs/{run_id}/events(SSE), GET /api/projects/{id}/outline.

## 단계 3. 내레이션, 자막, SRT
- pipeline/narration.py: 장면별 내레이션을 글자 수 예산에 맞춰 생성한다.
- pipeline/subtitles.py: 자막을 한 줄 16자, 최대 2줄로 나누고, 장면 시간을 글자 수에 비례해 큐마다 배분한다. 단어 중간에서 끊지 않는다. 수정 요청 에이전트의 split_subtitles도 이 함수를 쓴다.
- export/srt.py와 GET /api/projects/{id}/export?format=srt. PATCH /api/narrations/{id}는 LLM 없이 자막을 코드로 즉시 다시 나눈다.

## 단계 4. 맞춤 매뉴얼, 주의사항, 일정
- pipeline/manual.py: 대상과 난이도에 맞는 매뉴얼 단계와 주의사항, 단계별 소요 기간을 생성한다. 수치는 원고에 있는 값만 쓴다.
- pipeline/schedule.py: 일정은 시작일 기준 며칠째인지로 저장하고, 코드가 매뉴얼 단계 순서대로 배치한다.
- export/csv_ics.py(CSV, ICS), export/docx_export.py(스토리보드와 매뉴얼 DOCX), export?format=json. 매뉴얼과 일정 조회·수정 API를 만든다.

## 단계 5. 검수와 수정 정책
- pipeline/checks.py: 설계서 10절의 C01~C12를 구현하고 결과를 review_check에 저장한다. 실패하면 설계서의 "실패했을 때" 칸대로 해당 단계만 1회 다시 요청하고, 그래도 실패하면 경고로 남긴다. 경고 표현 목록(C10)과 과장·단정 표현 목록(C12)은 backend/app/rules/warning_terms.txt와 backend/app/rules/hype_terms.txt로 두고 초안 단어를 채워 둔다.
- 10절의 수정·재생성 규칙 1~5를 구현한다. PATCH 장면·매뉴얼 단계·일정 항목, POST /api/scenes/{id}/regenerate(edited_fields 필드는 덮어쓰지 않음), PUT scene-order, revision 기록, 사람 확인 H01~H03 저장, GET /api/runs/{id}/checks, GET·PUT /api/prompts/{stage}를 만든다.
- 설계서 11절 순서와 달리 검수를 화면보다 먼저 만든다는 점을 decisions.md에 남긴다. 결과 화면의 검수 패널이 이 데이터를 쓰기 때문이다.

## 단계 6. 화면
- frontend에 Vite, React, TypeScript, TanStack Query, Tailwind로 설계서 5절의 화면 5개(프로젝트 목록, 자료 입력, 조건 설정, 생성 진행, 결과 작업공간)를 만든다. 모든 문구는 한국어다.
- 결과 작업공간은 5절 와이어프레임을 따른다. 위쪽에 제목과 "전체 다시 생성", "내보내기" 버튼, 탭 다섯 개(구성안, 스토리보드, 내레이션·자막, 매뉴얼·일정, 검수), 본문은 왼쪽 장면 목록(검수 상태 점 포함), 가운데 편집 영역("이 장면만 다시 생성", "수정 저장"), 오른쪽 검수 패널(자동 검수와 사람 확인 체크박스)이다.
- 자료 입력 화면은 원문과 정제본을 나란히 보여 주고 문단을 합치거나 나눌 수 있게 한다. 생성 진행 화면은 SSE로 단계별 상태와 실패 사유를 보여 준다.
- API 주소는 frontend/.env의 VITE_API_BASE(기본 http://localhost:8000)로 둔다. 마지막에 npm run build가 성공하는지 확인한다.

## 단계 7. 수정 요청 에이전트 연결
- agent/repo.py: edit_agent.py의 Repo 프로토콜을 SQLAlchemy로 구현한다. split_subtitles는 단계 3의 함수를, check는 단계 5의 검수 함수를 쓴다.
- 설계서 6절과 13절의 API 다섯 개(수정 요청 접수, 에이전트 SSE, 제안 조회, 승인, 거절)를 만든다. 모든 도구 호출은 agent_action에, 제안은 change_proposal에 저장한다. 승인하면 필드를 바꾸고 revision을 남기며, 내레이션 제안이면 자막을 다시 나눈다.
- 결과 작업공간에 수정 요청 입력창, 에이전트가 부르는 도구의 진행 표시, 제안별 전후 비교와 승인·거절 버튼을 붙인다. 사용자가 고친 필드를 바꾸는 제안에는 경고 표시를 한다.

## 단계 8. 실제 모델 확인과 평가 도구
- docs/eval/sample_drill.txt에 합성 샘플 원고(전동드릴 안전교육, 1,500자 안팎, 제목과 목록과 표가 섞인 형태)를 만든다.
- scripts/smoke_ollama.py: 샘플 원고로 구성안부터 매뉴얼까지 한 번 생성하고 단계별 JSON 성공 여부, 재요청 횟수, 걸린 시간, 토큰 수, 잘림 위험을 표로 출력한다. --model 옵션으로 qwen3:8b와 exaone3.5:7.8b를 비교할 수 있게 한다. 이 스크립트는 네가 실행하지 말고, 내가 실행할 명령어를 알려 준 뒤 멈춘다.
- docs/eval/requests.json 형식(요청 문장, 대상 장면, 기대 도구 순서, 기대 결과, 거절해야 하는지)을 정하고 설계서 13절 평가 표에 맞춰 20개 초안을 만든다. 기대 결과는 내가 확정한다고 표시한다.
- scripts/run_eval.py: requests.json을 돌려 도구 선택 정확도, 제안 통과율, 거절 정확도, 평균 도구 호출 수를 docs/eval/report.md로 낸다. 결과보고서용 지표(생성 시간, 검수 통과율, 사용자 수정 횟수)를 agent_step_log와 revision에서 뽑는 scripts/report_metrics.py도 만든다.
- 마지막으로 README.md에 설치부터 실행까지의 순서를 정리하고, 내가 해야 할 남은 일을 목록으로 보고한다.
```

## 2. 이어서 하기

대화가 끊겼거나 새 대화에서 이어 갈 때 쓴다.

```text
CLAUDE.md, docs/progress.md, docs/decisions.md를 읽고 git log --oneline -20으로 어디까지 했는지 확인해라. 마지막으로 끝나지 않은 단계부터 PROMPT.md의 "1. 시작 프롬프트"에 적힌 진행 방식과 단계 설명대로 이어서 진행해라. 시작하기 전에 pytest를 먼저 돌려 지금 상태가 통과하는지 확인하고, 실패하는 테스트가 있으면 그것부터 고쳐라.
```

## 3. 실제 모델 확인 (단계 8 이후, Ollama에 모델을 받은 뒤)

`ollama pull qwen3:8b`와 `ollama pull exaone3.5:7.8b`를 먼저 해 둔다. smoke_ollama.py는 직접 실행하고 출력 전체를 붙여 넣는다.

```text
내가 scripts/smoke_ollama.py를 두 모델로 실행한 결과를 아래에 붙인다. 두 모델의 JSON 성공률, 재요청 횟수, 장면당 생성 시간, 잘림 위험을 비교해 docs/eval/model_test.md에 표로 정리하고, 어느 모델을 기본값으로 둘지 근거와 함께 추천해라. 잘림 위험이 있었다면 OLLAMA_NUM_CTX를 얼마로 올릴지와 그때 필요한 VRAM을 함께 적어라. 내 노트북 GPU는 [GPU 이름], VRAM은 [용량]이다.

[여기에 출력 붙여 넣기]
```

## 4. 호롱불 원고가 왔을 때

받은 파일을 `docs/eval/originals/`에 넣은 뒤 쓴다. 이 폴더는 저장소에 올라가지 않는다.

```text
docs/eval/originals/에 호롱불에서 받은 실제 원고와 결과물을 넣었다. 다음을 해라.
1. 원고마다 text_cleaner.clean_file을 돌려 문단 수, 문단 길이 분포, 제목 후보 수, 표 문단 수, 제거한 줄 수를 표로 보고하고, 잘못 나뉘거나 잘못 이어진 곳을 원문 위치와 함께 찾아라.
2. 문제가 있으면 규칙을 고치되, 테스트에는 실제 원고 문장을 넣지 말고 같은 모양의 합성 문장으로 테스트를 추가해라.
3. 받은 결과물(스토리보드, 대본, 자막)이 있으면 우리 출력 스키마와 필드를 비교하고, 양식에 맞추려면 무엇을 바꿔야 하는지 목록으로 정리해라. 스키마나 DB를 바꿔야 하면 바꾸기 전에 나에게 묻는다.
4. 결과물에서 한 줄 자막 글자 수, 줄 수, 말하기 속도를 확인할 수 있으면 config.py의 기본값과 비교해 보고해라.
```

## 5. 호롱불 규칙과 양식을 반영할 때

```text
호롱불에서 받은 규칙은 다음과 같다. [한 줄 자막 글자 수, 줄 수, 자막 파일 형식, 말하기 속도, 영상 길이, 필수 문구, 금지·과장 표현, 용어 표기 규칙을 적는다]
config.py의 기본값, 경고 표현 목록, 과장·단정 표현 목록, 프롬프트 템플릿에 반영하고, 프롬프트를 바꿨다면 prompt_template에 새 버전으로 저장해라. 바꾼 값과 근거를 docs/decisions.md에 남기고, 영향을 받는 테스트를 고친 뒤 pytest를 통과시켜라.
```

## 6. 수정 요청 에이전트 평가

docs/eval/requests.json의 기대 결과를 직접 확정한 뒤 쓴다.

```text
docs/eval/requests.json의 기대 결과를 확정했다. scripts/run_eval.py로 평가를 돌릴 명령어를 알려 줘. 내가 실행한 결과(docs/eval/report.md)를 보고, 틀린 요청마다 원인이 시스템 프롬프트, 도구 설명, 가드레일, 모델 한계 중 무엇인지 분류하고 고칠 방법을 제안해라. 고친 뒤 다시 평가해 이전 결과와 비교한 표를 report.md 끝에 붙여라.
```
