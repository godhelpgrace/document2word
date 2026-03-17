"""
Preview session storage for interactive OCR selection.
"""

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from config import settings


class PreviewStore:
    """Stores preview images and OCR metadata on disk."""

    def __init__(self) -> None:
        self.base_dir = Path(settings.STORAGE_BASE_DIR) / "previews"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, input_path: str) -> str:
        session_id = str(uuid.uuid4())
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "session_id": session_id,
            "input_path": input_path,
            "pages": [],
        }
        (session_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
        return session_id

    def _load_meta(self, session_id: str) -> dict:
        meta_path = self.base_dir / session_id / "meta.json"
        if not meta_path.exists():
            return {}
        return json.loads(meta_path.read_text())

    def _save_meta(self, session_id: str, meta: dict) -> None:
        meta_path = self.base_dir / session_id / "meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False))

    def save_page(
        self,
        session_id: str,
        page_index: int,
        page_number: int,
        width: float,
        height: float,
        image_bytes: bytes,
        ocr_results: list[dict[str, Any]],
    ) -> str:
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        image_path = session_dir / f"page_{page_index + 1}.png"
        image_path.write_bytes(image_bytes)

        meta = self._load_meta(session_id)
        pages = meta.get("pages", [])
        pages.append(
            {
                "page_index": page_index,
                "page_number": page_number,
                "width": width,
                "height": height,
                "image_path": str(image_path),
                "ocr_results": ocr_results,
            }
        )
        meta["pages"] = pages
        self._save_meta(session_id, meta)
        return str(image_path)

    def save_result_page(self, session_id: str, page_index: int, image_bytes: bytes) -> str:
        session_dir = self.base_dir / session_id / "results"
        session_dir.mkdir(parents=True, exist_ok=True)
        image_path = session_dir / f"result_{page_index + 1}.png"
        image_path.write_bytes(image_bytes)

        meta = self._load_meta(session_id)
        pages = meta.get("pages", [])
        for page in pages:
            if page.get("page_index") == page_index:
                page["result_image_path"] = str(image_path)
                break
        meta["pages"] = pages
        self._save_meta(session_id, meta)
        return str(image_path)

    def get_result_image_path(self, session_id: str, page_index: int) -> Optional[Path]:
        meta = self._load_meta(session_id)
        for page in meta.get("pages", []):
            if page.get("page_index") == page_index:
                path = page.get("result_image_path")
                return Path(path) if path else None
        return None

    def get_session(self, session_id: str) -> dict:
        return self._load_meta(session_id)

    def get_image_path(self, session_id: str, page_index: int) -> Optional[Path]:
        meta = self._load_meta(session_id)
        for page in meta.get("pages", []):
            if page.get("page_index") == page_index:
                path = page.get("image_path")
                return Path(path) if path else None
        return None


preview_store = PreviewStore()
