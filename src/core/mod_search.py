"""Shared, local-only search for installed mod metadata."""

import re
from dataclasses import dataclass

from src.core.game_registry import lookup_game_title, serial_matches_query
from src.models.mod import ModInfo


MOD_SEARCH_HINT = 'All words must match • "phrases" • author:Alice • tag:hd • -demo'
MOD_SEARCH_HELP = (
    "Search across metadata, game titles/aliases, tags, files, and paths.\n"
    "Words may match different fields; double quotes keep a phrase together.\n"
    "Fields: name:, author:, game:, serial:, tag:, file:, source:, path:, "
    "description:, version:, type:, id:.\n"
    'Example: game:"GTA III" tag:hd -author:Demo\n'
    "Prefix a term or field with - to exclude it. Quote a whole token to search "
    "literally, e.g. \"-demo\" or \"author:Alice\".\n"
    "Matching ignores case and punctuation. URLs, backslashes, and apostrophes "
    "remain literal; an unfinished double quote is accepted while typing."
)

_TOKENS = re.compile(r'(?:[^\s"]+|"[^"]*(?:"|$))+')
_FIELDS = {
    "name": "name", "author": "author", "game": "game", "serial": "serial",
    "tag": "tag", "tags": "tag", "file": "file", "files": "file",
    "source": "source", "url": "source", "path": "path",
    "description": "description", "desc": "description",
    "version": "version", "type": "type", "id": "id",
}


def _compact(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum())


@dataclass(frozen=True)
class _Term:
    field: str
    text: str
    compact: str
    excluded: bool


@dataclass(frozen=True)
class ModSearchQuery:
    terms: tuple[_Term, ...]
    valid: bool = True

    def matches(self, mod: ModInfo) -> bool:
        if not self.valid:
            return False
        if not self.terms:
            return True

        # Per-match caches cannot become stale after metadata edits or imports.
        normalized = {}
        titles = {}

        def values(field):
            if field == "game":
                if field not in titles:
                    titles[field] = lookup_game_title(mod.game_id) if mod.game_id else ""
                return (mod.game_id, titles[field])
            if field == "serial":
                return (mod.game_id,)
            if field == "tag":
                tags = getattr(mod, "tags", [])
                return tags if isinstance(tags, (list, tuple)) else ()
            if field == "file":
                files = getattr(mod, "files", [])
                return files if isinstance(files, (list, tuple)) else ()
            if field == "source":
                return (mod.source_url,)
            if field == "type":
                return (getattr(mod.mod_type, "value", ""),)
            if field == "thumbnail":
                return (mod.thumbnail_url, mod.thumbnail_path)
            return (getattr(mod, field, ""),)

        def matches_field(term, field):
            for value in values(field):
                if not isinstance(value, str):
                    continue
                if value not in normalized:
                    lowered = value.casefold()
                    normalized[value] = (lowered, _compact(lowered))
                lowered, compact = normalized[value]
                if term.text in lowered or (term.compact and term.compact in compact):
                    return True
            return False

        def matches_term(term):
            fields = (term.field,) if term.field else (
                "name", "author", "description", "serial", "version", "source",
                "type", "id", "tag", "path", "thumbnail", "game",
            )
            if any(matches_field(term, field) for field in fields):
                return True
            if term.field in ("", "game") and isinstance(mod.game_id, str) and mod.game_id:
                if serial_matches_query(mod.game_id, term.text):
                    return True
            return not term.field and matches_field(term, "file")

        return all(matches_term(term) != term.excluded for term in self.terms)


def compile_mod_query(query: object) -> ModSearchQuery:
    """Parse once per filter pass; quotes never escape paths or require closing."""
    if not isinstance(query, str):
        return ModSearchQuery((), valid=False)
    terms = []
    for match in _TOKENS.finditer(query):
        raw = match.group()
        excluded = raw.startswith("-") and len(raw) > 1
        if excluded:
            raw = raw[1:]
        field = ""
        prefix, separator, remainder = raw.partition(":")
        if separator and prefix.casefold() in _FIELDS and remainder.replace('"', ""):
            field = _FIELDS[prefix.casefold()]
            raw = remainder
        text = raw.replace('"', "").casefold()
        if text:
            terms.append(_Term(field, text, _compact(text), excluded))
    return ModSearchQuery(tuple(terms))


def mod_matches_query(mod: ModInfo, query: object) -> bool:
    return compile_mod_query(query).matches(mod)
