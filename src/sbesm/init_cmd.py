from pathlib import Path

from sbesm.config import StorageConfig, write_storage_config
from sbesm.identity import generate_storage_id
from sbesm.paths import validate_root_candidate


def cmd_init(root: Path, name: str | None = None) -> StorageConfig:
    root = Path(root)
    validate_root_candidate(root)

    root.mkdir(parents=True, exist_ok=True)
    sbesm_dir = root / ".sbesm"
    sbesm_dir.mkdir()

    storage_id = generate_storage_id()
    config = StorageConfig(id=storage_id, name=name or root.name)

    write_storage_config(sbesm_dir / "config.toml", config)
    (sbesm_dir / "storage_id").write_text(storage_id)

    return config
