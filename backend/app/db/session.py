# session.py : DB 연결과 세션.
# 엔진은 처음 쓸 때 만든다. DATABASE_URL이 없어도 앱과 순수 로직 테스트는 import만으로 깨지지 않게 하기 위해서다.
# 테스트는 configure()로 TEST_DATABASE_URL에 다시 연결한다.
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import config

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def configure(url: str) -> Engine:
    """엔진을 새로 만든다. pool_pre_ping은 MySQL이 오래 쉰 연결을 끊었을 때 다시 연결하게 한다.
    pool_recycle 3600초는 MySQL 기본 wait_timeout(8시간)보다 충분히 짧게 잡은 값이다."""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, future=True)
    _factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL이 없습니다. 저장소 루트의 .env를 확인해 주세요.")
        configure(config.DATABASE_URL)
    assert _engine is not None
    return _engine


def SessionLocal() -> Session:
    """백그라운드 스레드(생성 실행, 수정 요청 에이전트)처럼 요청 밖에서 쓰는 세션을 만든다."""
    get_engine()
    assert _factory is not None
    return _factory()


def get_db() -> Iterator[Session]:
    """FastAPI 의존성. 요청 하나에 세션 하나를 쓰고 끝나면 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
