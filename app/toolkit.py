"""Per-worker toolkits from a host-vetted catalog (docs/vision-gap.md §2.3).

Two layers:

- The **catalog** is what *may* be granted on this host: the two built-in
  web tools, the MCP servers listed in `catalog.json` at the repo root (you
  or the crew add entries there; nothing is vetted by default), and the
  skills under `worker_templates/skills/`.
- A worker's **toolkit** (`workers/<name>/toolkit.json`) is what has been
  attached to it: tools, MCP servers and read-only folders that every spawn
  applies on top of per-spawn grants, plus the skills installed in its
  `.claude/skills/`. Nothing is in a toolkit until someone puts it there.
"""

from __future__ import annotations

import json
from pathlib import Path

TOOLKIT_FILE = "toolkit.json"
BUILTIN_TOOLS = {
    "WebSearch": "Search the web (Claude Code's built-in tool).",
    "WebFetch": "Fetch and read a web page (Claude Code's built-in tool).",
}
EMPTY = {"tools": [], "mcp_servers": [], "read_from": [], "skills": []}


class BadToolkit(ValueError):
    """A toolkit names something the catalog does not offer."""


def parse_frontmatter_description(text: str) -> str:
    if text.startswith("---"):
        for line in text.split("\n")[1:]:
            if line.strip() == "---":
                break
            if line.startswith("description:"):
                return line.split(":", 1)[1].strip()
    return ""


def load_catalog(catalog_file: Path, skills_dir: Path) -> dict:
    """{"tools": {name: {description}}, "mcp_servers": {name: {description,
    type, command, args, env...}}, "skills": {name: {description, path}}}."""
    servers: dict = {}
    if catalog_file.is_file():
        data = json.loads(catalog_file.read_text(encoding="utf-8"))
        for name, entry in (data.get("mcp_servers") or {}).items():
            if not isinstance(entry, dict) or "command" not in entry and "url" not in entry:
                raise ValueError(f"catalog mcp server {name!r} needs a command (stdio) or a url")
            servers[name] = entry
    skills: dict = {}
    if skills_dir.is_dir():
        for file in sorted(skills_dir.glob("*.md")):
            skills[file.stem] = {"description": parse_frontmatter_description(file.read_text(encoding="utf-8")), "path": file}
    return {
        "tools": {name: {"description": d} for name, d in BUILTIN_TOOLS.items()},
        "mcp_servers": servers,
        "skills": skills,
    }


def catalog_view(catalog: dict) -> dict:
    """The catalog as the API shows it: names and descriptions only (an MCP
    server's command is the host's business)."""
    return {
        kind: [{"name": n, "description": e.get("description", "")} for n, e in sorted(catalog[kind].items())]
        for kind in ("tools", "mcp_servers", "skills")
    }


def installed_skills(worker_folder: Path) -> list[str]:
    root = worker_folder / ".claude" / "skills"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "SKILL.md").is_file())


def read(worker_folder: Path) -> dict:
    """The worker's toolkit; skills are read from disk, the rest from the file."""
    kit = dict(EMPTY)
    file = worker_folder / TOOLKIT_FILE
    if file.is_file():
        stored = json.loads(file.read_text(encoding="utf-8"))
        for key in ("tools", "mcp_servers", "read_from"):
            kit[key] = list(stored.get(key) or [])
    kit["skills"] = installed_skills(worker_folder)
    return kit


def validate(kit: dict, catalog: dict) -> dict:
    """Normalise and check a toolkit against the catalog. `read_from` is
    checked by the API (it owns the grant rules). Raises BadToolkit."""
    out = {}
    for key in ("tools", "mcp_servers", "skills"):
        wanted = sorted(set(kit.get(key) or []))
        unknown = [n for n in wanted if n not in catalog[key]]
        if unknown:
            raise BadToolkit(f"bad_{key.rstrip('s')}: {unknown} (catalog: {sorted(catalog[key])})")
        out[key] = wanted
    out["read_from"] = list(kit.get("read_from") or [])
    return out


def write(worker_folder: Path, kit: dict, catalog: dict) -> dict:
    """Store the toolkit and install any listed skill that is missing (from
    the catalog's copy). Skills already installed stay; removing one is an
    explicit, separate action."""
    stored = {k: kit[k] for k in ("tools", "mcp_servers", "read_from")}
    (worker_folder / TOOLKIT_FILE).write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    for name in kit["skills"]:
        target = worker_folder / ".claude" / "skills" / name / "SKILL.md"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(catalog["skills"][name]["path"].read_text(encoding="utf-8"), encoding="utf-8")
    return read(worker_folder)


def remove_skill(worker_folder: Path, name: str) -> bool:
    """Uninstall one skill (its whole folder). False if it was not there."""
    import shutil

    folder = worker_folder / ".claude" / "skills" / name
    if not (folder / "SKILL.md").is_file():
        return False
    shutil.rmtree(folder)
    return True


def server_configs(names: list[str], catalog: dict) -> dict[str, dict]:
    """The MCP server definitions to hand to a session, minus the description."""
    return {n: {k: v for k, v in catalog["mcp_servers"][n].items() if k != "description"} for n in names}
