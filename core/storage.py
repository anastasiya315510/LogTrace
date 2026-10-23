import asyncio
from collections.abc import AsyncIterator
from typing import BinaryIO

import boto3
from botocore.config import Config

from core.config import get_settings

_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


def _make_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint or None,
        aws_access_key_id=settings.nebius_storage_access_key_id,
        aws_secret_access_key=settings.nebius_storage_secret_key,
        config=Config(signature_version="s3v4"),
    )


class ObjectStorage:
    """S3-compatible object storage client (Nebius Object Storage)."""

    def __init__(self):
        self._client = _make_client()
        self._bucket = get_settings().object_storage_bucket

    async def upload_fileobj(self, fileobj: BinaryIO, key: str) -> None:
        """Stream a file to object storage without loading it into memory."""
        await asyncio.to_thread(
            self._client.upload_fileobj,
            fileobj,
            self._bucket,
            key,
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )

    async def delete_objects(self, keys: list[str]) -> None:
        if not keys:
            return
        objects = [{"Key": k} for k in keys]
        await asyncio.to_thread(
            self._client.delete_objects,
            Bucket=self._bucket,
            Delete={"Objects": objects},
        )

    async def stream_object(self, key: str) -> AsyncIterator[bytes]:
        """Yield chunks of an object without loading it fully into memory."""

        def _get_body():
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"]

        body = await asyncio.to_thread(_get_body)

        def _read_chunk():
            return body.read(_CHUNK_SIZE)

        while chunk := await asyncio.to_thread(_read_chunk):
            yield chunk

    async def generate_presigned_upload_url(self, key: str, expires_in: int = 3600) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )


_storage: ObjectStorage | None = None


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        _storage = ObjectStorage()
    return _storage
