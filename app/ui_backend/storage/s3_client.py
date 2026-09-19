"""Object storage for audio chunks (MinIO or any S3-compatible service).

Keys are ``sessions/<session id>/chunks/<index>.webm``. boto3 is synchronous,
so callers run these methods in a thread (``run_in_executor`` /
``asyncio.to_thread``) to keep the event loop free.
"""

import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class S3Client:
    """Thin wrapper around a boto3 client bound to the configured bucket."""

    def __init__(self):
        """Create the client from the ``s3_*`` settings."""
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
        self.bucket = settings.s3_bucket

    def upload_chunk(self, session_id: str, chunk_index: int, data: bytes) -> str:
        """Store one chunk and return its object key."""
        key = f"sessions/{session_id}/chunks/{chunk_index}.webm"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="audio/webm",
        )
        logger.info(f"Uploaded chunk to s3://{self.bucket}/{key}")
        return key

    def download_chunk(self, key: str) -> bytes:
        """Read a whole object into memory."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete_object(self, bucket: str, key: str) -> bool:
        """Delete an object; an already-missing object counts as success."""
        try:
            self.client.delete_object(Bucket=bucket, Key=key)
            logger.info(f"Deleted s3://{bucket}/{key}")
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                logger.warning(f"Object already deleted: s3://{bucket}/{key}")
                return True
            logger.error(f"Error deleting s3://{bucket}/{key}: {e}")
            return False

    def stream_chunk(self, key: str):
        """Return a streaming body for an object (for HTTP pass-through)."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"]
        except ClientError as e:
            logger.error(f"Error streaming s3://{self.bucket}/{key}: {e}")
            raise


s3_client = S3Client()
