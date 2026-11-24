import hashlib
import re
import uuid
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        filename: str,
        data: bytes,
        content_type: str = "",
    ) -> tuple[str, int, str]:
        safe_name = _SAFE_FILENAME.sub("_", Path(filename).name)[:160] or "artifact"
        key = f"{project_id}/{run_id}/{uuid.uuid4().hex[:12]}-{safe_name}"
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key, len(data), hashlib.sha256(data).hexdigest()

    def read(self, key: str) -> bytes:
        root = self.root.resolve()
        path = (root / key).resolve()
        if root not in path.parents:
            raise ValueError("非法的存储路径")
        return path.read_bytes()


@lru_cache
def get_storage() -> LocalStorage:
    return LocalStorage(Path(get_settings().storage_dir))
