from datetime import UTC, datetime
from pathlib import Path

from sbesm.config import read_storage_config
from sbesm.errors import UsageError
from sbesm.fsident import check_storage_id_marker
from sbesm.registry import RegistryEntry, upsert_entry
from sbesm.xdg import config_home


def cmd_register(
    root: Path, name: str | None = None, registry_path: Path | None = None
) -> RegistryEntry:
    root = Path(root)
    sbesm_dir = root / ".sbesm"
    if not sbesm_dir.is_dir():
        raise UsageError(
            f"{root} is not an initialized SBESM storage (no .sbesm directory)"
        )

    config = read_storage_config(sbesm_dir / "config.toml")
    check_storage_id_marker(config, sbesm_dir)

    entry = RegistryEntry(
        name=name or config.name,
        storage_id=config.id,
        last_known_root=str(root.resolve()),
        filesystem_uuid=config.filesystem_uuid,
        last_seen_at=datetime.now(UTC).isoformat(),
    )

    path = registry_path if registry_path is not None else (config_home() / "registry.toml")
    upsert_entry(path, entry)
    return entry
