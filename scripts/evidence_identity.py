"""Inspect individual, explicitly authorized project evidence files."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from . import safe_state_write as guard
else:
    import safe_state_write as guard


FILE_LIMIT = 1024 * 1024
SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,95}\Z")
SOURCE_MARKER = re.compile(r"\[source_id:([A-Za-z0-9][A-Za-z0-9:._-]{0,95})\]")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
LIMITATIONS = ("only file content verified",)


class EvidenceError(ValueError):
    """A malformed identity or an unverifiable file."""


def references(text):
    return SOURCE_MARKER.findall(text)


def _parts(relative_path):
    if not isinstance(relative_path, str):
        raise EvidenceError("evidence path must be a project-relative string")
    parts = relative_path.split("/")
    if (len(relative_path) > 512 or any(
        not part or part in (".", "..") or part.endswith((" ", "."))
        or re.search(r"[\\:<>\"|?*\x00-\x1f]", part) or _reserved(part)
        for part in parts
    )):
        raise EvidenceError("invalid relative evidence path")
    return parts


def _reserved(part):
    return re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])",
                        part.split(".")[0].upper().rstrip(" ")) is not None


@dataclass(frozen=True)
class Identity:
    source_id: str
    relative_path: str
    sha256: str
    observed_at: str
    scope: str = "current-project"
    limitations: tuple[str, ...] = LIMITATIONS

    def __post_init__(self):
        if not isinstance(self.source_id, str) or not SOURCE_ID.fullmatch(self.source_id):
            raise EvidenceError("invalid evidence source ID")
        _parts(self.relative_path)
        if not isinstance(self.sha256, str) or not SHA256.fullmatch(self.sha256):
            raise EvidenceError("invalid evidence SHA-256")
        try:
            instant = datetime.fromisoformat(self.observed_at)
        except (ValueError, TypeError) as exc:
            raise EvidenceError("invalid evidence observation time") from exc
        if instant.tzinfo is None or self.scope != "current-project":
            raise EvidenceError("evidence requires an offset timestamp and current-project scope")
        if not isinstance(self.limitations, (tuple, list)) or not all(
            isinstance(item, str) and item and len(item) <= 250 for item in self.limitations
        ) or len(self.limitations) > 8:
            raise EvidenceError("invalid evidence limitations")
        object.__setattr__(self, "limitations", tuple(self.limitations))

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict):
            raise EvidenceError("evidence identity must be an object")
        fields = {name: value for name, value in data.items() if name != "status"}
        try:
            return cls(**fields)
        except TypeError as exc:
            raise EvidenceError("invalid evidence identity fields") from exc

    def to_dict(self):
        return {**asdict(self), "status": "valid"}


def _stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _checked_path(root, relative_path, excluded):
    root = Path(root)
    if not root.is_absolute() or ".." in root.parts:
        raise EvidenceError("project root must be an authorized absolute directory")
    parts = _parts(relative_path)
    try:
        path = guard.managed_path(root.joinpath(*parts), root=root)
    except guard.PathBoundaryError as exc:
        raise EvidenceError("invalid scoped evidence file") from exc
    if excluded is not None and path.parent.resolve().is_relative_to(Path(excluded).resolve()):
        raise EvidenceError("memory bodies and snapshots are outside project evidence scope")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > FILE_LIMIT:
        raise EvidenceError("evidence is not a supported regular file")
    return path, info


def _read_project_file(root, relative_path, *, excluded=None):
    path, before = _checked_path(root, relative_path, excluded)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags | getattr(os, "O_NONBLOCK", 0)), "rb") as handle:
        opened = os.fstat(handle.fileno())
        _, current = _checked_path(root, relative_path, excluded)
        if _stamp(opened) != _stamp(before) or _stamp(current) != _stamp(before):
            raise EvidenceError("evidence changed while opening")
        data = handle.read(FILE_LIMIT + 1)
        after = os.fstat(handle.fileno())
    _, current = _checked_path(root, relative_path, excluded)
    if (len(data) != before.st_size or _stamp(after) != _stamp(before) or
            _stamp(current) != _stamp(before) or after.st_ctime_ns != opened.st_ctime_ns or
            current.st_ctime_ns != before.st_ctime_ns):
        raise EvidenceError("evidence changed while reading")
    return data


def observe(root, source_id, relative_path, *, excluded=None):
    """Capture bytes only for a source the caller has verified is eligible."""
    if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id):
        raise EvidenceError("invalid evidence source ID")
    data = _read_project_file(root, relative_path, excluded=excluded)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return Identity(source_id, relative_path, hashlib.sha256(data).hexdigest(), now)


def verify(root, identity, *, excluded=None):
    """Return the four-state verification result and bytes only on an exact match."""
    try:
        data = _read_project_file(root, identity.relative_path, excluded=excluded)
    except FileNotFoundError:
        return "missing", None
    except (OSError, EvidenceError):
        return "unknown", None
    if hashlib.sha256(data).hexdigest() != identity.sha256:
        return "stale", None
    return "valid", data
