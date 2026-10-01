# conftest.py : DB가 필요한 테스트의 공통 준비.
# TEST_DATABASE_URL이 있을 때만 DB 테스트가 돈다. 없으면 db·client 픽스처를 쓰는 테스트는 skip된다.
# 테스트 DB에는 매 세션 처음에 db/schema.sql을 그대로 적용하고, 테스트마다 모든 테이블을 비운 뒤
# seed.sql과 같은 테스트 사용자 한 명을 넣는다. 운영 DB(content_ai)와 다른 DB를 써야 한다.
import os

import pytest
from sqlalchemy import text

from app.db import schema_sql, session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture(scope="session")
def db_engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL이 없어 MySQL이 필요한 테스트를 건너뛴다")
    engine = session.configure(TEST_DATABASE_URL)
    names = schema_sql.table_names()
    with engine.begin() as conn:
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        for name in reversed(names):
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS `{name}`")
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
        for stmt in schema_sql.table_statements():
            conn.exec_driver_sql(stmt)
    yield engine


@pytest.fixture
def db(db_engine):
    with db_engine.begin() as conn:
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        for name in schema_sql.table_names():
            conn.exec_driver_sql(f"TRUNCATE TABLE `{name}`")
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
        conn.execute(text("INSERT INTO app_user (id, name, email) VALUES (1, '테스트 사용자', 'tester@example.com')"))
    s = session.SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c
