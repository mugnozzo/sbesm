import sqlite3
from pathlib import Path

from sbesm.config import StorageConfig, write_storage_config
from sbesm.errors import StorageUnavailableError
from sbesm.fsident import detect_filesystem_uuid, is_mounted_and_responsive
from sbesm.identity import generate_storage_id
from sbesm.paths import validate_root_candidate


def cmd_init(root: Path, name: str | None = None) -> StorageConfig:
    root = Path(root)
    validate_root_candidate(root)

    liveness_check_path = root if root.exists() else root.parent
    if not is_mounted_and_responsive(liveness_check_path):
        raise StorageUnavailableError(
            f"{liveness_check_path} is not mounted or not responding"
        )

    root.mkdir(parents=True, exist_ok=True)
    sbesm_dir = root / ".sbesm"
    sbesm_dir.mkdir()

    storage_id = generate_storage_id()
    filesystem_uuid = detect_filesystem_uuid(root)
    config = StorageConfig(
        id=storage_id, name=name or root.name, filesystem_uuid=filesystem_uuid
    )

    write_storage_config(sbesm_dir / "config.toml", config)
    (sbesm_dir / "storage_id").write_text(storage_id)

    (sbesm_dir / "logs").mkdir()
    sqlite3.connect(sbesm_dir / "index.sqlite").close()

    return config
