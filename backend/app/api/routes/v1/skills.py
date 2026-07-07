"""Skills endpoints — ClawHub catalog proxy + per-user install + upload.

A "skill" is a directory containing a ``SKILL.md`` (and optional helper
files). The agent's ``SkillsToolset`` scans the user's skill directory at
chat time and exposes each skill's tools to the LLM.

Per-user skills live at ``MEDIA_DIR/skills/<user_id>/<skill_name>/``. The
``SkillsToolset`` is configured to load from there (see
:mod:`app.agents.assistant`).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/skills", tags=["skills"])

CLAWHUB_CATALOG_URL = "https://clawhub.ai/api/skills?sort=downloads"


def _skills_root(user_id: str) -> Path:
    """Return (creating if needed) the per-user skills directory."""
    root = Path(settings.MEDIA_DIR) / "skills" / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _skill_dir(user_id: str, name: str) -> Path:
    """Return the path to a single installed skill."""
    # Skill names are directory names — sanitise to alnum + dash/underscore.
    safe = "".join(c for c in name if c.isalnum() or c in "-_").lower()
    if not safe:
        raise HTTPException(400, "Invalid skill name")
    return _skills_root(user_id) / safe


def _parse_skill_md(skill_path: Path) -> dict[str, Any]:
    """Read a SKILL.md and extract the front-matter (name, description)."""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return {"name": skill_path.name, "description": "", "installed": True}
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"name": skill_path.name, "description": "", "installed": True}

    # Naive YAML front-matter parser: pull lines between leading --- fences.
    name = skill_path.name
    description = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            front = text[3:end].strip()
            for line in front.splitlines():
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k = k.strip().lower()
                v = v.strip().strip("\"'")
                if k == "name":
                    name = v
                elif k == "description":
                    description = v
    # Use the first non-empty line of the body as a fallback description.
    if not description:
        body = text.split("---", 2)[-1].strip() if text.startswith("---") else text.strip()
        for line in body.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                description = line[:200]
                break
    return {"name": name, "description": description, "installed": True}


@router.get("/installed")
async def list_installed_skills(current_user: CurrentUser) -> Any:
    """List the user's installed skills (parsed from disk)."""
    root = _skills_root(str(current_user.id))
    out = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        info = _parse_skill_md(child)
        info["path"] = child.name
        out.append(info)
    return {"skills": out}


@router.get("/catalog")
async def clawhub_catalog(current_user: CurrentUser) -> Any:
    """Proxy the ClawHub skill catalog so the frontend can render a one-click
    install grid. Mark each entry with ``installed`` based on the user's
    on-disk skills.

    Falls back to a built-in starter catalog when the ClawHub API is
    unreachable (offline dev, network restrictions, etc.) or returns an
    unexpected payload. The fallback is ALWAYS merged in so the user sees
    at least the starter skills.
    """
    user_root = _skills_root(str(current_user.id))
    installed = {p.name for p in user_root.iterdir() if p.is_dir()} if user_root.exists() else set()

    items: list[dict[str, Any]] = []
    source = "fallback"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(CLAWHUB_CATALOG_URL)
            if resp.status_code < 400:
                try:
                    data = resp.json()
                    raw = data if isinstance(data, list) else data.get("skills", [])
                    if isinstance(raw, list) and raw:
                        items = raw
                        source = "clawhub"
                except Exception:
                    # JSON parse failed — fall through to fallback below.
                    pass
    except Exception as exc:
        logger.warning("ClawHub catalog fetch failed, using built-in fallback: %s", exc)

    # Always merge the builtin catalog so the page is never empty. If ClawHub
    # returned real entries, we prepend them (ClawHub first, builtin after).
    builtin = _builtin_catalog()
    seen_names = {i.get("name") or i.get("slug") for i in items if isinstance(i, dict)}
    for entry in builtin:
        if entry.get("name") not in seen_names:
            items.append(entry)

    # Normalise + tag with installed state.
    normalised = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("slug") or item.get("id")
        if not name:
            continue
        normalised.append(
            {
                "name": str(name),
                "description": str(item.get("description") or item.get("summary") or ""),
                "downloads": int(item.get("downloads") or item.get("download_count") or 0),
                "url": str(item.get("url") or f"https://clawhub.ai/skills/{name}"),
                "installed": str(name) in installed,
            }
        )
    return {"skills": normalised, "source": source}


@router.post("/install/{skill_name}")
async def install_skill_from_catalog(
    skill_name: str,
    current_user: CurrentUser,
) -> Any:
    """Fetch a skill from ClawHub and install it locally.

    The ClawHub download URL convention is ``https://clawhub.ai/skills/<name>/download``.
    We fetch the .zip, extract into the user's skills dir, and parse its
    SKILL.md so the SkillsToolset picks it up on the next chat turn.
    """
    safe = "".join(c for c in skill_name if c.isalnum() or c in "-_").lower()
    if not safe:
        raise HTTPException(400, "Invalid skill name")

    target = _skill_dir(str(current_user.id), safe)
    if target.exists():
        return {"installed": True, "name": safe, "message": "Already installed"}

    download_url = f"https://clawhub.ai/skills/{safe}/download"
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(download_url)
            if resp.status_code >= 400:
                raise HTTPException(
                    404,
                    f"Skill '{safe}' not found on ClawHub (HTTP {resp.status_code})",
                )
            data = resp.content
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch skill from ClawHub: {exc}") from exc

    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(target)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(400, f"Downloaded file was not a valid zip: {exc}") from exc

    # Some zips nest the skill in a top-level folder — flatten it.
    children = list(target.iterdir())
    if len(children) == 1 and children[0].is_dir():
        nested = children[0]
        for sub in nested.iterdir():
            shutil.move(str(sub), str(target / sub.name))
        nested.rmdir()

    info = _parse_skill_md(target)
    return {"installed": True, "name": safe, **info}


@router.delete("/{skill_name}")
async def uninstall_skill(skill_name: str, current_user: CurrentUser) -> Any:
    """Remove an installed skill from the user's directory."""
    target = _skill_dir(str(current_user.id), skill_name)
    if not target.exists():
        raise HTTPException(404, "Skill not installed")
    await asyncio.to_thread(shutil.rmtree, target)
    return {"uninstalled": True, "name": target.name}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_skill(
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """Upload a ``.zip`` or ``SKILL.md`` file to install as a skill.

    For a ``.zip``: extract into ``skills/<user_id>/<name>/``. The zip may
    either contain a single top-level folder (whose name becomes the skill
    name) or the SKILL.md at its root (in which case the zip filename minus
    extension becomes the skill name).

    For a ``SKILL.md``: install as ``skills/<user_id>/<filename>/SKILL.md``.
    """
    if not file.filename:
        raise HTTPException(400, "Filename required")
    fname = file.filename.lower()
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")

    user_root = _skills_root(str(current_user.id))

    if fname.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise HTTPException(400, f"Invalid zip: {exc}") from exc

        # Determine skill name from the top-level folder or filename.
        names = zf.namelist()
        top = next((n for n in names if n.rstrip("/")), "")
        skill_name = (
            top.split("/")[0]
            if top and "/" in top
            else file.filename.rsplit(".", 1)[0]
        )
        skill_name = "".join(c for c in skill_name if c.isalnum() or c in "-_").lower()
        if not skill_name:
            raise HTTPException(400, "Could not derive skill name from zip")

        target = user_root / skill_name
        target.mkdir(parents=True, exist_ok=True)
        try:
            zf.extractall(target)
        except Exception as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise HTTPException(400, f"Failed to extract zip: {exc}") from exc

        # Flatten a single nested folder (matches ClawHub install behaviour).
        children = list(target.iterdir())
        if len(children) == 1 and children[0].is_dir():
            nested = children[0]
            for sub in nested.iterdir():
                shutil.move(str(sub), str(target / sub.name))
            nested.rmdir()

        info = _parse_skill_md(target)
        return {"installed": True, "name": skill_name, **info}

    if fname.endswith(".md") or "skill" in fname:
        skill_name = file.filename.rsplit(".", 1)[0]
        skill_name = "".join(c for c in skill_name if c.isalnum() or c in "-_").lower()
        if not skill_name:
            raise HTTPException(400, "Could not derive skill name from filename")
        target = user_root / skill_name
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_bytes(raw)
        info = _parse_skill_md(target)
        return {"installed": True, "name": skill_name, **info}

    raise HTTPException(400, "Upload must be a .zip or SKILL.md file")


@router.get("/{skill_name}/SKILL.md")
async def read_skill_md(skill_name: str, current_user: CurrentUser) -> Any:
    """Return the raw SKILL.md contents for an installed skill."""
    target = _skill_dir(str(current_user.id), skill_name)
    skill_md = target / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(404, "SKILL.md not found for this skill")
    return StreamingResponse(
        io.BytesIO(skill_md.read_bytes()),
        media_type="text/markdown",
        headers={"Content-Disposition": f'inline; filename="SKILL.md"'},
    )


# ----------------------------------------------------------------- fallback
# A small built-in catalog used when ClawHub is unreachable. Each entry is a
# placeholder we can't actually download — but the frontend can render them
# so the page isn't empty in offline dev. The user can still upload a .zip.

def _builtin_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "charts",
            "description": "Generate matplotlib / seaborn charts as PNG (publication-quality).",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/charts",
        },
        {
            "name": "pdf",
            "description": "Generate PDF reports (ReportLab / LaTeX). Includes academic + creative pipelines.",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/pdf",
        },
        {
            "name": "xlsx",
            "description": "Read, write, and analyse Excel spreadsheets with embedded charts.",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/xlsx",
        },
        {
            "name": "docx",
            "description": "Create and edit Word documents with tracked-changes support.",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/docx",
        },
        {
            "name": "pptx",
            "description": "Build slide decks as standalone HTML or PPTX.",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/pptx",
        },
        {
            "name": "image-generation",
            "description": "AI image generation capabilities (text-to-image, edits, variations).",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/image-generation",
        },
        {
            "name": "web-search",
            "description": "Real-time web search and content extraction.",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/web-search",
        },
        {
            "name": "web-reader",
            "description": "Extract clean article content from any URL.",
            "downloads": 0,
            "url": "https://clawhub.ai/skills/web-reader",
        },
    ]


__all__ = ["router"]
