# models.py가 db/schema.sql과 1:1로 맞는지 실제 MySQL에서 확인한다(TEST_DATABASE_URL이 있을 때만).
from sqlalchemy import inspect

from app.db import models, schema_sql


def test_models_match_schema_sql(db_engine):
    insp = inspect(db_engine)
    assert sorted(insp.get_table_names()) == sorted(schema_sql.table_names())
    assert len(schema_sql.table_names()) == 21
    for name, table in models.Base.metadata.tables.items():
        db_cols = {c["name"]: c for c in insp.get_columns(name)}
        model_cols = {c.name: c for c in table.columns}
        assert set(db_cols) == set(model_cols), f"{name} 컬럼이 다르다"
        for col_name, col in model_cols.items():
            assert db_cols[col_name]["nullable"] == col.nullable, f"{name}.{col_name} NULL 허용 여부가 다르다"
        db_fks = {(fk["constrained_columns"][0], fk["referred_table"]) for fk in insp.get_foreign_keys(name)}
        model_fks = {(fk.parent.name, fk.column.table.name) for fk in table.foreign_keys}
        assert db_fks == model_fks, f"{name} 외래키가 다르다"
