# env.py : Alembic 실행 환경. 접속 주소는 app.config(저장소 루트 .env의 DATABASE_URL)에서 읽는다.
from alembic import context
from sqlalchemy import create_engine, pool

from app import config
from app.db.models import Base

# autogenerate가 비교할 기준. models.py가 schema.sql과 1:1이므로 이후 변경도 모델 기준으로 만들 수 있다.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """DB에 접속하지 않고 SQL 문장만 출력한다(alembic upgrade head --sql)."""
    context.configure(url=config.DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """DB에 접속해 변경을 적용한다. 마이그레이션은 한 번만 도는 작업이라 연결 풀을 쓰지 않는다(NullPool)."""
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL이 없습니다. 저장소 루트의 .env를 확인해 주세요.")
    engine = create_engine(config.DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
