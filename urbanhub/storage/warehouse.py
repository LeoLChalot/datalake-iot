"""Accès à l'entrepôt PostgreSQL (tables structurées + vues pour Metabase)."""
from __future__ import annotations

import io
import logging
from functools import cached_property

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from urbanhub import config

log = logging.getLogger(__name__)

INIT_SQL = config.PROJECT_ROOT / "sql" / "init.sql"


class Warehouse:
    def __init__(self, schema: str = config.POSTGRES_SCHEMA):
        self.schema = schema

    @cached_property
    def engine(self) -> Engine:
        url = (
            f"postgresql+psycopg2://{config.POSTGRES_USER}:{config.POSTGRES_PASSWORD}"
            f"@{config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}"
        )
        return create_engine(url, pool_size=8, max_overflow=8, pool_pre_ping=True)

    def init_schema(self) -> None:
        """Crée le schéma, les tables et les vues (idempotent)."""
        sql = INIT_SQL.read_text(encoding="utf-8").replace("{schema}", self.schema)
        raw = self.engine.raw_connection()
        try:
            with raw.cursor() as cur:
                cur.execute(sql)
            raw.commit()
        finally:
            raw.close()
        log.info("Schéma %s initialisé", self.schema)

    def execute(self, sql: str, **params) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(sql.replace("{schema}", self.schema)), params)

    def read_sql(self, sql: str, **params) -> pd.DataFrame:
        with self.engine.connect() as conn:
            return pd.read_sql(text(sql.replace("{schema}", self.schema)), conn, params=params)

    def upsert(self, df: pd.DataFrame, table: str, key_cols: list[str], update: bool = True) -> int:
        """Insertion massive via COPY dans une table temporaire puis INSERT ... ON CONFLICT.

        Bien plus rapide que DataFrame.to_sql pour des millions de lignes, et idempotent :
        relancer une ingestion ne crée pas de doublons.
        """
        if df.empty:
            return 0
        df = df.drop_duplicates(subset=key_cols, keep="last")
        cols = list(df.columns)
        col_list = ", ".join(f'"{c}"' for c in cols)
        target = f'"{self.schema}"."{table}"'
        tmp = f"tmp_{table}"

        if update and set(cols) - set(key_cols):
            sets = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in key_cols)
            conflict = f"DO UPDATE SET {sets}"
        else:
            conflict = "DO NOTHING"

        buf = io.StringIO()
        df.to_csv(buf, index=False, header=False, na_rep="\\N")
        buf.seek(0)

        raw = self.engine.raw_connection()
        try:
            with raw.cursor() as cur:
                cur.execute(f"CREATE TEMP TABLE {tmp} (LIKE {target} INCLUDING DEFAULTS) ON COMMIT DROP")
                cur.copy_expert(f"COPY {tmp} ({col_list}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
                cur.execute(
                    f"INSERT INTO {target} ({col_list}) SELECT {col_list} FROM {tmp} "
                    f"ON CONFLICT ({', '.join(key_cols)}) {conflict}"
                )
                count = cur.rowcount
            raw.commit()
        finally:
            raw.close()
        return count

    def table_counts(self) -> pd.DataFrame:
        return self.read_sql(
            """
            SELECT relname AS table_name, n_live_tup AS lignes_estimees
            FROM pg_stat_user_tables WHERE schemaname = :schema ORDER BY relname
            """,
            schema=self.schema,
        )
