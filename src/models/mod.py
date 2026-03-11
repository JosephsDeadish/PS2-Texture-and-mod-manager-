"""Data models for PS2 Mod Manager."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import json
import time


class ModType(Enum):
    TEXTURE_PACK = "texture_pack"
    PNACH = "pnach"
    COVER_ART = "cover_art"
    SAVE_FILE = "save_file"
    CHEAT = "cheat"


class ModStatus(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    CONFLICT = "conflict"


@dataclass
class ModInfo:
    """Represents a single mod/content item."""
    id: str
    name: str
    mod_type: ModType
    path: str
    enabled: bool = True
    version: str = "1.0.0"
    author: str = "Unknown"
    description: str = ""
    game_id: str = ""
    thumbnail_url: str = ""
    thumbnail_path: str = ""
    source_url: str = ""
    priority: int = 0
    files: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    size_bytes: int = 0
    installed: bool = True
    has_update: bool = False
    installed_at: float = field(default_factory=time.time)  # Unix timestamp

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mod_type": self.mod_type.value,
            "path": self.path,
            "enabled": self.enabled,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "game_id": self.game_id,
            "thumbnail_url": self.thumbnail_url,
            "thumbnail_path": self.thumbnail_path,
            "source_url": self.source_url,
            "priority": self.priority,
            "files": self.files,
            "tags": self.tags,
            "size_bytes": self.size_bytes,
            "installed": self.installed,
            "has_update": self.has_update,
            "installed_at": self.installed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModInfo":
        data = dict(data)
        data["mod_type"] = ModType(data["mod_type"])
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class ConflictInfo:
    """Represents a conflict between two mods."""
    mod_a_id: str
    mod_b_id: str
    conflicting_files: list = field(default_factory=list)
    resolution: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "mod_a_id": self.mod_a_id,
            "mod_b_id": self.mod_b_id,
            "conflicting_files": self.conflicting_files,
            "resolution": self.resolution,
        }


@dataclass
class AppConfig:
    """Application configuration."""
    pcsx2_path: str = ""
    textures_path: str = ""
    pnach_path: str = ""
    cover_art_path: str = ""
    memcards_path: str = ""
    cheats_path: str = ""
    partial_textures_path: str = ""
    mods_storage_path: str = ""
    game_library_path: str = ""
    theme: str = "dark"
    check_updates_on_start: bool = True
    show_conflict_warnings: bool = True
    first_run: bool = True
    favorite_authors: list = field(default_factory=list)
    show_nsfw: bool = False
    show_paid: bool = False
    show_account_required: bool = True
    show_incomplete: bool = True

    def to_dict(self) -> dict:
        return {
            "pcsx2_path": self.pcsx2_path,
            "textures_path": self.textures_path,
            "pnach_path": self.pnach_path,
            "cover_art_path": self.cover_art_path,
            "memcards_path": self.memcards_path,
            "cheats_path": self.cheats_path,
            "partial_textures_path": self.partial_textures_path,
            "mods_storage_path": self.mods_storage_path,
            "game_library_path": self.game_library_path,
            "theme": self.theme,
            "check_updates_on_start": self.check_updates_on_start,
            "show_conflict_warnings": self.show_conflict_warnings,
            "first_run": self.first_run,
            "favorite_authors": self.favorite_authors,
            "show_nsfw": self.show_nsfw,
            "show_paid": self.show_paid,
            "show_account_required": self.show_account_required,
            "show_incomplete": self.show_incomplete,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
