"""Accès au Data Lake MinIO (API S3).

Organisation du bucket (architecture « médaillon ») :

    bronze/   données brutes, telles que reçues des sources (CSV, JSON compressés)
    silver/   données nettoyées et typées (Parquet)

La couche « gold » (indicateurs prêts à l'emploi) vit dans PostgreSQL.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
from functools import cached_property

import boto3
import pandas as pd
from botocore.client import Config
from botocore.exceptions import ClientError

from urbanhub import config

log = logging.getLogger(__name__)


class DataLake:
    def __init__(self, bucket: str = config.MINIO_BUCKET):
        self.bucket = bucket

    @cached_property
    def client(self):
        return boto3.client(
            "s3",
            endpoint_url=config.MINIO_ENDPOINT,
            aws_access_key_id=config.MINIO_ACCESS_KEY,
            aws_secret_access_key=config.MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4", max_pool_connections=64),
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
            log.info("Bucket %s créé", self.bucket)

    # ------------------------------------------------------------------ écriture
    def put_bytes(self, key: str, data: bytes, compress: bool = False) -> str:
        if compress:
            data = gzip.compress(data)
            key = key if key.endswith(".gz") else key + ".gz"
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def put_json(self, key: str, obj, compress: bool = True) -> str:
        return self.put_bytes(key, json.dumps(obj, ensure_ascii=False).encode("utf-8"), compress)

    def put_parquet(self, key: str, df: pd.DataFrame) -> str:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=buf.getvalue())
        return key

    # ------------------------------------------------------------------- lecture
    def get_bytes(self, key: str) -> bytes:
        data = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return gzip.decompress(data) if key.endswith(".gz") else data

    def read_parquet(self, prefix: str) -> pd.DataFrame:
        """Lit et concatène tous les fichiers Parquet sous un préfixe."""
        frames = [pd.read_parquet(io.BytesIO(self.get_bytes(k))) for k in self.list_keys(prefix) if k.endswith(".parquet")]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def list_keys(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def summary(self) -> pd.DataFrame:
        """Volume stocké par zone/source (pour la démo et le notebook)."""
        rows = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for obj in page.get("Contents", []):
                parts = obj["Key"].split("/")
                rows.append({"zone": parts[0], "source": parts[1] if len(parts) > 1 else "", "size": obj["Size"]})
        if not rows:
            return pd.DataFrame(columns=["zone", "source", "fichiers", "taille_mo"])
        df = pd.DataFrame(rows)
        out = df.groupby(["zone", "source"]).agg(fichiers=("size", "size"), taille_mo=("size", "sum")).reset_index()
        out["taille_mo"] = (out["taille_mo"] / 1e6).round(1)
        return out
