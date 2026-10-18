import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from sbesm.config import read_storage_config
from sbesm.errors import IOFailureError, UsageError


@dataclass
class UninitPreview:
    root: Path
    sbesm_dir: Path
    log_file_count: int
    storage_id: str | None


def cmd_uninit(root: Path, apply: bool = False) -> UninitPreview:
    root = Path(root)
    sbesm_dir = root / ".sbesm"
    if not sbesm_dir.is_dir():
        raise UsageError(f"{root} has no .sbesm directory; nothing to uninit")

    logs_dir = sbesm_dir / "logs"
    log_file_count = len(list(logs_dir.glob("*.log"))) if logs_dir.is_dir() else 0

    storage_id: str | None = None
    config_path = sbesm_dir / "config.toml"
    if config_path.exists():
        try:
            storage_id = read_storage_config(config_path).id
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            storage_id = None

    preview = UninitPreview(
        root=root, sbesm_dir=sbesm_dir, log_file_count=log_file_count, storage_id=storage_id
    )

    if apply:
        try:
            shutil.rmtree(sbesm_dir)
        except OSError as exc:
            raise IOFailureError(f"failed to remove {sbesm_dir}: {exc}") from exc

    return preview
