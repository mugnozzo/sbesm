from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from sbesm.db import connect, get_file_row, upsert_file_row
from sbesm.errors import UsageError
from sbesm.hashing import hash_file_stable


@dataclass
class AcceptResult:
    relative_path: str
    old_hash: str | None
    new_hash: str
    applied: bool = False


def cmd_accept(
    root: Path, db_path: Path, relative_path: str, apply: bool = False
) -> AcceptResult:
    conn = connect(db_path)
    try:
        existing = get_file_row(conn, relative_path)
        if existing is None:
            raise UsageError(f"{relative_path!r} is not an indexed file in this storage")
        if existing.kind != "regular":
            raise UsageError(
                f"{relative_path!r} is not a regular file (kind={existing.kind}); "
                f"accept only applies to hashable regular files"
            )

        absolute_path = root / relative_path
        try:
            fresh_hash = hash_file_stable(absolute_path)
        except FileNotFoundError as exc:
            raise UsageError(
                f"{relative_path!r} does not exist on disk; "
                f"cannot accept a reference for a missing file"
            ) from exc

        result = AcceptResult(relative_path, existing.reference_sha256, fresh_hash)

        if apply:
            now = datetime.now(UTC).isoformat()
            st = absolute_path.lstat()
            row = replace(
                existing,
                reference_sha256=fresh_hash,
                reference_size=st.st_size,
                reference_mtime_ns=st.st_mtime_ns,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                hashed_at=now,
                last_seen_at=now,
                state="indexed",
                candidate_sha256=None,
            )
            upsert_file_row(conn, row)
            conn.commit()
            result = replace(result, applied=True)

        return result
    finally:
        conn.close()
