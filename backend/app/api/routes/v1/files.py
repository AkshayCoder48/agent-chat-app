
"""File upload and download endpoints for chat attachments."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.agents.tools.workspace_tools import (
    _resolve_safe,
    _workspace_root,
    zip_folder,
)
from app.api.deps import CurrentUser, FileUploadSvc
from app.core.exceptions import NotFoundError
from app.schemas.file import FileInfo, FileUploadResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """Upload a file for use in chat."""
    data = await file.read()
    chat_file = await file_upload_svc.upload(
        user_id=current_user.id,
        file_data=data,
        filename=file.filename or "unknown",
        content_type=file.content_type,
    )
    return FileUploadResponse(
        id=chat_file.id,
        filename=chat_file.filename,
        mime_type=chat_file.mime_type,
        size=chat_file.size,
        file_type=chat_file.file_type,
    )


@router.get("/{file_id}", response_model=None)
async def download_file(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
    disposition: str = "inline",
) -> Any:
    """Serve a file. Only the owner can access their files.

    By default the response is ``Content-Disposition: inline`` so PDFs, images
    and audio/video render directly inside an ``<iframe>`` / media tag (used
    by the chat file-preview panel). Pass ``?disposition=attachment`` to force
    the browser's download dialog (used by the explicit "Download" button).
    """
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from None

    file_path = file_upload_svc.get_file_path(chat_file.storage_path)
    if not file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")

    # FastAPI's ``FileResponse(filename=...)`` always uses ``attachment`` —
    # build the header manually so we can switch to ``inline`` for previews.
    mode = "attachment" if disposition == "attachment" else "inline"
    safe_name = chat_file.filename.replace('"', "")
    # The chat file-preview panel embeds this URL in an iframe (PDFs, HTML,
    # etc). Default ``X-Frame-Options: DENY`` from SecurityHeadersMiddleware
    # would break that, so opt this endpoint down to SAMEORIGIN. The CSP
    # ``frame-ancestors 'self'`` is the modern equivalent — browsers honor
    # whichever they recognize.
    headers = {
        "Content-Disposition": f'{mode}; filename="{safe_name}"',
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
    }
    return FileResponse(path=file_path, media_type=chat_file.mime_type, headers=headers)


@router.get("/{file_id}/info", response_model=FileInfo)
async def get_file_info(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
) -> Any:
    """Get file metadata. Only the owner can access."""
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from None

    return FileInfo(
        id=chat_file.id,
        filename=chat_file.filename,
        mime_type=chat_file.mime_type,
        size=chat_file.size,
        file_type=chat_file.file_type,
        created_at=chat_file.created_at,
        user_id=chat_file.user_id,
    )


# --------------------------------------------------------------- workspace DL
# Endpoints the agent's ``send_file`` / ``send_folder`` tools build URLs for.
# Per-user workspace lives under ``MEDIA_DIR/workspaces/<user_id>/`` — see
# ``app.agents.tools.workspace_tools``. Only the owner may fetch from their
# workspace; paths are resolved and verified to stay inside the root.


@router.get("/workspace/{user_id}/download")
async def download_workspace_file(
    user_id: UUID,
    current_user: CurrentUser,
    path: str = Query(..., description="Relative path inside the user's workspace"),
) -> Any:
    """Serve a single file from the user's workspace."""
    # Only the owner may read their workspace.
    if str(user_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your workspace")

    root = _workspace_root(str(current_user.id))
    try:
        target = _resolve_safe(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    safe_name = target.name.replace('"', "")
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Frame-Options": "SAMEORIGIN",
    }
    return FileResponse(path=str(target), headers=headers)


@router.get("/workspace/{user_id}/download-folder")
async def download_workspace_folder(
    user_id: UUID,
    current_user: CurrentUser,
    path: str = Query(..., description="Relative folder path inside the user's workspace"),
) -> Any:
    """Zip a folder on the fly and serve it as a download."""
    if str(user_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your workspace")

    root = _workspace_root(str(current_user.id))
    try:
        target = _resolve_safe(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if not target.exists() or target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    zip_path = await _safe_zip(root, target)
    safe_name = f"{target.name}.zip".replace('"', "")
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Frame-Options": "SAMEORIGIN",
    }
    return FileResponse(path=str(zip_path), media_type="application/zip", headers=headers)


async def _safe_zip(root, folder):
    """Run the blocking zip in a thread so the event loop isn't held."""
    import asyncio

    return await asyncio.to_thread(zip_folder, root, folder)


@router.get("/workspace/{user_id}/list", response_model=None)
async def list_workspace(
    user_id: UUID,
    current_user: CurrentUser,
    path: str = Query(".", description="Relative path inside the user's workspace"),
) -> Any:
    """List the contents of a workspace directory (used by the file sidebar)."""
    if str(user_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your workspace")

    root = _workspace_root(str(current_user.id))
    try:
        target = _resolve_safe(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path not found")
    if target.is_file():
        return {
            "path": path,
            "entries": [
                {"name": target.name, "type": "file", "size": target.stat().st_size}
            ],
        }

    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_file(), p.name.lower())):
        try:
            st = child.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "type": "folder" if child.is_dir() else "file",
                "size": st.st_size if child.is_file() else None,
            }
        )
    return {"path": path, "entries": entries}


# --------------------------------------------------------------- workspace (self)
# Same as the ``/workspace/{user_id}`` routes above, but the user_id is
# inferred from the auth token. The frontend file sidebar uses these — it
# doesn't know the user's UUID, only that it's the logged-in user.


@router.get("/workspace/list", response_model=None)
async def list_own_workspace(
    current_user: CurrentUser,
    path: str = Query(".", description="Relative path inside the user's workspace"),
) -> Any:
    """List the contents of the calling user's workspace directory."""
    root = _workspace_root(str(current_user.id))
    try:
        target = _resolve_safe(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Path not found")
    if target.is_file():
        return {
            "path": path,
            "absolute": str(target),
            "parent": str(target.parent.relative_to(root)) if target.parent != root else None,
            "entries": [
                {"name": target.name, "type": "file", "size": target.stat().st_size}
            ],
        }

    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_file(), p.name.lower())):
        try:
            st = child.stat()
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "type": "folder" if child.is_dir() else "file",
                "size": st.st_size if child.is_file() else None,
            }
        )
    parent_rel = (
        str(target.parent.relative_to(root)) if target != root and target.parent != root else None
    )
    return {
        "path": path,
        "absolute": str(target),
        "parent": parent_rel,
        "entries": entries,
    }


@router.get("/workspace/download")
async def download_own_workspace_file(
    current_user: CurrentUser,
    path: str = Query(..., description="Relative path inside the user's workspace"),
) -> Any:
    """Serve a single file from the calling user's workspace."""
    root = _workspace_root(str(current_user.id))
    try:
        target = _resolve_safe(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    headers = {
        "Content-Disposition": f'inline; filename="{target.name}"',
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
    }
    return FileResponse(path=str(target), filename=target.name, headers=headers)


@router.get("/workspace/download-folder")
async def download_own_workspace_folder(
    current_user: CurrentUser,
    path: str = Query(..., description="Relative folder path inside the user's workspace"),
) -> Any:
    """Zip a folder from the calling user's workspace and stream it back."""
    import asyncio

    root = _workspace_root(str(current_user.id))
    try:
        target = _resolve_safe(root, path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    if not target.exists() or not target.is_file():
        # Allow zipping the root too — but require it to be a directory.
        if not target.is_dir():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    elif target.is_file():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path is a file, not a folder")

    return await asyncio.to_thread(zip_folder, root, target)
