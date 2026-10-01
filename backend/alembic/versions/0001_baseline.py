"""기준 리비전: db/schema.sql의 테이블 21개

이미 schema.sql로 DB를 만든 경우에는 이 리비전을 실행하지 말고 `alembic stamp head`로 표시만 한다.
빈 DB에서 처음부터 만들 때만 `alembic upgrade head`가 schema.sql의 CREATE TABLE 문장을 차례로 실행한다.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-01
"""
from alembic import op

from app.db import schema_sql

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # schema.sql 하나를 기준으로 삼기 위해 테이블 정의를 여기에 다시 쓰지 않고 파일에서 읽어 실행한다.
    for stmt in schema_sql.table_statements():
        op.execute(stmt)


def downgrade() -> None:
    # 외래키 순서를 신경 쓰지 않고 지우도록 검사를 잠시 끈다. 만든 순서의 반대로 지운다.
    op.execute("SET FOREIGN_KEY_CHECKS = 0")
    for name in reversed(schema_sql.table_names()):
        op.execute(f"DROP TABLE IF EXISTS `{name}`")
    op.execute("SET FOREIGN_KEY_CHECKS = 1")
