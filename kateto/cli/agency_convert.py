from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Agency-agents frontmatter is flat `key: value` (name, description, color,
# emoji, vibe, ...) with no nested structures, so a tiny regex split is enough
# — no PyYAML dependency.
_FRONTMATTER = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Filesystem-safe id: lowercase, non-alnum -> '-', collapse, strip '-'."""
    slug = _NON_SLUG.sub("-", name.strip().casefold())
    return slug.strip("-")


def _parse_agent(text: str) -> tuple[dict[str, str], str]:
    """Split an agency-agents .md into (frontmatter fields, body)."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text.strip()
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip().casefold()] = value.strip()
    return fields, text[match.end() :].strip()


def _resolve_source(source: str, cache_root: Path) -> Path:
    """Return a local dir for a git URL or local path, clone-or-pull as needed."""
    local = Path(source)
    if local.exists():
        return local.resolve()
    cache = cache_root / local.stem.replace(".git", "")
    if cache.is_dir():
        subprocess.run(["git", "-C", str(cache), "pull", "--ff-only"], check=False)
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", source, str(cache)], check=True)
    return cache


def clone_agency_repo(url: str, cache_dir: Path) -> Path:
    """Clone-or-pull an agency-agents git repo into cache_dir."""
    return _resolve_source(url, cache_root=cache_dir)


def convert_agency_pack(
    repo_dir: Path,
    out_dir: Path,
    *,
    divisions: list[str] | None = None,
    force: bool = False,
) -> list[str]:
    """Convert an agency-agents repo into a Kateto pack (voices/ + skills/).

    Each division dir holding *.md agent files becomes that many voices. The
    voice id is the file stem without the `<division>-` prefix, slugified
    (falling back to the frontmatter name). Returns the ids written.
    """
    converted: list[str] = []
    want = {d.casefold() for d in divisions} if divisions else None
    for division in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
        if want is not None and division.name.casefold() not in want:
            continue
        if not any(division.glob("*.md")):
            continue
        for agent_file in sorted(division.glob("*.md")):
            fields, body = _parse_agent(agent_file.read_text(encoding="utf-8"))
            stem = agent_file.stem
            rest = stem[len(division.name) + 1 :] if stem.startswith(division.name + "-") else stem
            voice_id = _slugify(rest) or _slugify(fields.get("name", ""))
            if not voice_id:
                continue  # no safe id derivable; skip
            soul = out_dir / "voices" / voice_id / "SOUL.md"
            skill = out_dir / "skills" / voice_id / "SKILL.md"
            if not force and (soul.exists() or skill.exists()):
                continue
            description = fields.get("description", "")
            soul.parent.mkdir(parents=True, exist_ok=True)
            skill.parent.mkdir(parents=True, exist_ok=True)
            soul.write_text(body or description, encoding="utf-8")
            skill.write_text(
                f"---\nname: {voice_id}\n---\n\n{description}\n\n"
                f"This skill loads the matching voice {voice_id!r} from this pack.\n",
                encoding="utf-8",
            )
            converted.append(voice_id)
    return converted
