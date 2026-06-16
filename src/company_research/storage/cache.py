from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from company_research.models.sources import RawDocument


class RawCache:
    """Content-addressed file cache for raw documents.

    Files are stored at <root>/<hash[:2]>/<hash> to avoid huge flat directories.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, content_hash: str) -> Path:
        return self.root / content_hash[:2] / content_hash

    def exists(self, content_hash: str) -> bool:
        return self._path_for(content_hash).exists()

    def store_bytes(
        self,
        data: bytes,
        source_id: str,
        mime_type: str,
    ) -> RawDocument:
        content_hash = hashlib.sha256(data).hexdigest()
        dest = self._path_for(content_hash)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        return RawDocument(
            doc_id=content_hash,   # stable: same content → same doc_id → idempotent ChromaDB upsert
            source_id=source_id,
            content_hash=content_hash,
            file_path=str(dest),
            mime_type=mime_type,
            size_bytes=len(data),
            retrieved_at=datetime.utcnow(),
        )

    def store_file(
        self,
        src: Path,
        source_id: str,
        mime_type: str,
    ) -> RawDocument:
        data = src.read_bytes()
        return self.store_bytes(data, source_id, mime_type)

    def read(self, content_hash: str) -> bytes:
        path = self._path_for(content_hash)
        if not path.exists():
            raise FileNotFoundError(f"Cache miss: {content_hash}")
        return path.read_bytes()

    def read_text(self, content_hash: str, encoding: str = "utf-8") -> str:
        return self.read(content_hash).decode(encoding, errors="replace")
