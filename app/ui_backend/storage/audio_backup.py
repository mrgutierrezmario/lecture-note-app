"""Stream the audio bucket in and out as a tar archive (used by deploy/backup.sh).

Runs *inside* the app container, where the S3 credentials already are, so the
backup script on the host never needs MinIO's password or a bind mount:

    docker compose exec -T app python -m storage.audio_backup export < have.txt > audio.tar
    docker compose exec -T app python -m storage.audio_backup import < audio.tar

``export`` reads the list of objects the host already has ("<key> <size>" per
line) on stdin and writes a tar of the *missing* objects to stdout, plus a
``MANIFEST`` entry listing every object in the bucket so the host can delete
local copies of chunks that retention has since removed. Modification times
are preserved, so an rclone sync afterwards uploads only what changed.

``import`` does the reverse: reads a tar on stdin and uploads each member to
the bucket (an object that already exists with the same size is skipped).
"""

import io
import sys
import tarfile
from datetime import UTC, datetime

from storage.s3_client import s3_client

MANIFEST = "MANIFEST"


def _list_objects() -> dict[str, tuple[int, datetime]]:
    """Every object in the bucket → (size, last modified)."""
    found: dict[str, tuple[int, datetime]] = {}
    paginator = s3_client.client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_client.bucket):
        for obj in page.get("Contents", []):
            found[obj["Key"]] = (obj["Size"], obj["LastModified"])
    return found


def export() -> None:
    """Write a tar of objects missing from the host's list to stdout."""
    have: dict[str, int] = {}
    for line in sys.stdin:
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            have[parts[0]] = int(parts[1])

    objects = _list_objects()
    out = sys.stdout.buffer
    with tarfile.open(fileobj=out, mode="w|") as tar:
        manifest = "\n".join(f"{key} {size}" for key, (size, _) in sorted(objects.items()))
        data = manifest.encode()
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(data)
        info.mtime = int(datetime.now(UTC).timestamp())
        tar.addfile(info, io.BytesIO(data))

        sent = 0
        for key, (size, modified) in objects.items():
            if have.get(key) == size:
                continue
            body = s3_client.download_chunk(key)
            info = tarfile.TarInfo(key)
            info.size = len(body)
            info.mtime = int(modified.timestamp())
            tar.addfile(info, io.BytesIO(body))
            sent += 1
    print(f"{len(objects)} objects in bucket, {sent} new", file=sys.stderr)


def import_() -> None:
    """Upload every member of the tar on stdin to the bucket."""
    existing = {key: size for key, (size, _) in _list_objects().items()}
    uploaded = skipped = 0
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tar:
        for member in tar:
            key = member.name.removeprefix("./")
            if not member.isfile() or key == MANIFEST:
                continue
            if existing.get(key) == member.size:
                skipped += 1
                continue
            body = tar.extractfile(member).read()
            s3_client.client.put_object(
                Bucket=s3_client.bucket, Key=key, Body=body, ContentType="audio/webm"
            )
            uploaded += 1
    print(f"{uploaded} objects uploaded, {skipped} already present", file=sys.stderr)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "export":
        export()
    elif command == "import":
        import_()
    else:
        sys.exit("usage: python -m storage.audio_backup export|import")
