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

## 남은 단계

단계 2부터 단계 8까지 남아 있다.
