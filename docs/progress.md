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

## 남은 단계

단계 1부터 단계 8까지 남아 있다.
