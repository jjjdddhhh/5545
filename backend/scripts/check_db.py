# check_db.py : MySQL 준비가 끝났는지 확인한다.
# 확인 항목은 두 가지다. 서버 버전이 8.0.16 이상인지(utf8mb4_0900_ai_ci 정렬 규칙과 CHECK 제약이
# 그 버전부터 동작한다, 설계서 11절), 그리고 db/schema.sql의 테이블 21개가 모두 만들어졌는지다.
# 실행 방법(backend 폴더에서): python scripts/check_db.py
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
MIN_VERSION = (8, 0, 16)   # 설계서 11절의 최소 버전
EXPECTED_TABLES = {
    "app_user", "project", "source_document", "generation_setting", "prompt_template",
    "generation_run", "agent_step_log", "outline", "scene", "narration", "subtitle_cue",
    "quiz_item", "manual", "manual_step", "caution", "schedule_item", "review_check",
    "revision", "edit_request", "agent_action", "change_proposal",
}


def parse_version(raw: str) -> tuple[int, int, int]:
    """'8.0.46-0ubuntu0.24.04.4' 같은 문자열에서 앞의 숫자 세 개만 읽는다."""
    head = raw.split("-")[0]
    parts = [int(x) for x in head.split(".")[:3] if x.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", encoding="utf-8")
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL이 없습니다. 저장소 루트의 .env.example을 .env로 복사하고 비밀번호를 채워 주세요.")
        return 1
    engine = create_engine(url)
    db_name = make_url(url).database
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar_one()
            tables = {row[0] for row in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :db"), {"db": db_name})}
            users = conn.execute(text("SELECT COUNT(*) FROM app_user")).scalar_one() if "app_user" in tables else 0
    except Exception as exc:  # 연결 실패 원인(비밀번호, 서버 꺼짐 등)을 그대로 보여 준다
        print(f"DB에 연결하지 못했습니다: {exc}")
        return 1

    ok = True
    print(f"MySQL 버전: {version}")
    if parse_version(version) < MIN_VERSION:
        print("버전이 8.0.16보다 낮습니다. MySQL 8.0.16 이상으로 올려 주세요.")
        ok = False
    missing = sorted(EXPECTED_TABLES - tables)
    print(f"테이블 수: {len(tables & EXPECTED_TABLES)} / {len(EXPECTED_TABLES)}")
    if missing:
        print("빠진 테이블: " + ", ".join(missing))
        print("db/schema.sql을 다시 적용해 주세요: mysql -u root -p < db/schema.sql")
        ok = False
    if users == 0:
        print("app_user에 사용자가 없습니다. db/seed.sql을 넣어 주세요: mysql -u root -p content_ai < db/seed.sql")
        ok = False
    print("DB 준비가 끝났습니다." if ok else "DB 준비가 아직 끝나지 않았습니다.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
