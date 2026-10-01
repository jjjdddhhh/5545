# AI 콘텐츠 기획·제작 자동화 플랫폼 (웹 프로토타입)

교육 원고를 넣으면 구성안, 장면별 스토리보드, 내레이션·자막(SRT), 대상별 맞춤 매뉴얼과 수행 일정을 만들고, 사용자가 결과를 고쳐 쓰는 웹 프로토타입이다. 설계는 `docs/design.md`, 구현 규칙은 `CLAUDE.md`, 진행 상황은 `docs/progress.md`에 있다.

이 문서는 구현이 진행되면서 계속 채운다. 설치부터 실행까지의 전체 순서는 단계 8에서 정리한다.

## DB 스키마 이력(Alembic)

DB 구조의 기준은 `db/schema.sql`이다. Alembic은 이 파일 전체를 기준 리비전 `0001_baseline` 하나로 등록해 두었다.

- 이미 `db/schema.sql`로 DB를 만들었다면 리비전을 실행하지 말고 표시만 한다. backend 폴더에서 `alembic stamp head`를 실행한다.
- 빈 DB에서 처음 만들 때는 `alembic upgrade head`가 `db/schema.sql`의 CREATE TABLE 문장을 차례로 실행한다.
- 현재 표시된 리비전은 `alembic current`로 확인한다.
- 이후 스키마를 바꿀 때는 `db/schema.sql`과 `app/db/models.py`를 함께 고치고, `alembic revision -m "설명"`으로 새 리비전을 만든다.
