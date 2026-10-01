# schema_sql.py : db/schema.sql을 문장 단위로 읽는다.
# Alembic 기준 리비전과 DB 테스트가 같은 파일을 쓰게 해서, 스키마의 기준이 schema.sql 하나로 유지되게 한다.
import re
from pathlib import Path

from app.config import REPO_ROOT

SCHEMA_FILE = REPO_ROOT / "db" / "schema.sql"


def table_statements(path: Path = SCHEMA_FILE) -> list[str]:
    """CREATE TABLE 문장만 순서대로 돌려준다. CREATE DATABASE와 USE는 빼서 연결한 DB에 그대로 적용할 수 있게 한다.
    주석 안에도 세미콜론이 있을 수 있으므로(예: SELECT VERSION();) 주석을 먼저 지운 뒤 세미콜론으로 나눈다."""
    sql = path.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)
    statements = [s.strip() for s in sql.split(";")]
    return [s for s in statements if s.upper().startswith("CREATE TABLE")]


def table_names(path: Path = SCHEMA_FILE) -> list[str]:
    return [re.match(r"CREATE TABLE\s+`?(\w+)`?", s, re.IGNORECASE).group(1) for s in table_statements(path)]
