import hashlib
import json
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, cast

from typing_extensions import TypedDict


ALLOWED_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".py", ".js",
    ".jsx", ".ts", ".tsx", ".css", ".scss", ".html", ".xml", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".sql", ".sh", ".ps1", ".java",
    ".kt", ".swift", ".go", ".rs", ".c", ".h", ".cpp", ".hpp",
}


class FileRecord(TypedDict):
    id: str
    name: str
    extension: str
    content_type: str
    size: int
    sha256: str
    created_at: str
    text_length: int


class FileValidationError(ValueError):
    pass


class FileIntelligenceService:
    """ID-addressed upload store that never accepts caller-controlled paths."""

    def __init__(self, upload_dir: Path, index_file: Path, max_bytes: int) -> None:
        self.upload_dir = upload_dir.resolve()
        self.index_file = index_file.resolve()
        self.max_bytes = max_bytes
        self._lock = Lock()
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            self.index_file.write_text(
                json.dumps({"version": 1, "files": []}, indent=2),
                encoding="utf-8",
            )

    def _read_index(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.index_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("files", []), list):
                raise ValueError("Invalid file index")
            return cast(Dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"File index at '{self.index_file}' is unreadable; it was not overwritten."
            ) from exc

    def _write_index(self, data: Dict[str, Any]) -> None:
        temporary = self.index_file.with_suffix(f"{self.index_file.suffix}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.index_file)

    @staticmethod
    def _safe_name(filename: str) -> str:
        name = Path(filename.replace("\\", "/")).name.strip()
        if not name or name in {".", ".."}:
            raise FileValidationError("A valid filename is required.")
        return name[:240]

    def _stored_path(self, file_id: str, extension: str) -> Path:
        try:
            canonical_id = str(uuid.UUID(file_id))
        except ValueError as exc:
            raise FileValidationError("Invalid file id.") from exc
        candidate = (self.upload_dir / f"{canonical_id}{extension}").resolve()
        if candidate.parent != self.upload_dir:
            raise FileValidationError("Invalid storage path.")
        return candidate

    def save(self, filename: str, content_type: str, content: bytes) -> FileRecord:
        name = self._safe_name(filename)
        extension = Path(name).suffix.casefold()
        if extension not in ALLOWED_TEXT_EXTENSIONS:
            raise FileValidationError(
                f"Unsupported file type '{extension or 'none'}'. Upload text, Markdown, JSON, CSV, or source code."
            )
        if not content:
            raise FileValidationError("The uploaded file is empty.")
        if len(content) > self.max_bytes:
            raise FileValidationError(
                f"File exceeds the {self.max_bytes // (1024 * 1024)} MB limit."
            )
        text = self._decode(content)
        if extension == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise FileValidationError("The JSON document is not valid.") from exc
        file_id = str(uuid.uuid4())
        path = self._stored_path(file_id, extension)
        path.write_bytes(content)
        record: FileRecord = {
            "id": file_id,
            "name": name,
            "extension": extension,
            "content_type": content_type or mimetypes.guess_type(name)[0] or "text/plain",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "text_length": len(text),
        }
        with self._lock:
            data = self._read_index()
            cast(List[FileRecord], data.setdefault("files", [])).append(record)
            self._write_index(data)
        return cast(FileRecord, dict(record))

    @staticmethod
    def _decode(content: bytes) -> str:
        if b"\x00" in content[:4096]:
            raise FileValidationError("Binary files are not accepted by this endpoint.")
        for encoding in ("utf-8-sig", "utf-8", "utf-16"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise FileValidationError("The file encoding is not supported.")

    def list(self) -> List[FileRecord]:
        with self._lock:
            entries = list(cast(List[FileRecord], self._read_index().get("files", [])))
        entries.sort(key=lambda item: item["created_at"], reverse=True)
        return [cast(FileRecord, dict(item)) for item in entries]

    def get(self, file_id: str) -> Optional[FileRecord]:
        with self._lock:
            entries = cast(List[FileRecord], self._read_index().get("files", []))
            record = next((item for item in entries if item["id"] == file_id), None)
        return cast(Optional[FileRecord], dict(record) if record else None)

    def get_text(self, file_id: str, max_chars: int = 50_000) -> str:
        # Validate the identifier before consulting the index so path-like input
        # is rejected consistently rather than treated as a missing record.
        self._stored_path(file_id, "")
        record = self.get(file_id)
        if record is None:
            raise FileNotFoundError("Uploaded file was not found.")
        path = self._stored_path(record["id"], record["extension"])
        if not path.is_file():
            raise FileNotFoundError("Uploaded file content is missing.")
        text = self._decode(path.read_bytes())
        return text[: max(1, min(max_chars, 200_000))]

    def delete(self, file_id: str) -> bool:
        with self._lock:
            data = self._read_index()
            entries = cast(List[FileRecord], data.get("files", []))
            record = next((item for item in entries if item["id"] == file_id), None)
            if record is None:
                return False
            data["files"] = [item for item in entries if item["id"] != file_id]
            self._write_index(data)
        path = self._stored_path(record["id"], record["extension"])
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return True
