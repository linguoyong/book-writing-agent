"""文件树、文件读写与文件系统操作。"""

from __future__ import annotations

from ...fileops import FileConflictError, project_lock, refresh_source, write_project_text
from .common import (
    BINARY_EXT,
    HIDDEN_PARTS,
    IMAGE_MIME,
    MAX_INLINE_IMAGE,
    MAX_TEXT_INLINE,
    MAX_TREE_NODES,
    Any,
    FsCreateRequest,
    FsRenameRequest,
    HTTPException,
    Path,
    WriteFileRequest,
    _guard_visible,
    _require_project,
    _resolve_workspace_file,
    _tree_node,
    base64,
    git_status_map,
    read_text,
    router,
    shutil,
)

# ---------------------------------------------------------------- 文件


@router.get("/projects/{project_id}/tree")
def get_tree(project_id: str) -> list[dict[str, Any]]:
    """整个工作区的文件树（排除 .git/.index 等），带 git 状态标记。"""
    project = _require_project(project_id)
    root = Path(project["path"])
    if not root.exists():
        raise HTTPException(status_code=404, detail="项目目录不存在")
    git_map = git_status_map(root) if (root / ".git").exists() else {}
    budget = [MAX_TREE_NODES]
    return [_tree_node(root, root, git_map, budget)]


@router.get("/projects/{project_id}/file")
def read_file(project_id: str, path: str, head: int | None = None) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, path, "read")
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="文件不存在")

    suffix = target.suffix.lower()
    info = target.stat()
    size = info.st_size
    mtime = int(info.st_mtime * 1000)
    if suffix in IMAGE_MIME and size <= MAX_INLINE_IMAGE:
        encoded = base64.b64encode(target.read_bytes()).decode("ascii")
        return {
            "path": path,
            "kind": "image",
            "mime": IMAGE_MIME[suffix],
            "data_url": f"data:{IMAGE_MIME[suffix]};base64,{encoded}",
            "size": size,
            "mtime": mtime,
        }
    if suffix in BINARY_EXT or suffix in IMAGE_MIME:
        return {"path": path, "kind": "binary", "size": size, "mtime": mtime}
    if head is None and size > MAX_TEXT_INLINE:
        # 百万字级别的稿件整份塞进编辑器会卡死，先让用户选择只读分段预览
        return {"path": path, "kind": "large", "size": size, "mtime": mtime}
    content = read_text(target)
    truncated = False
    if head is not None and len(content) > head:
        content = content[:head]
        truncated = True
    return {
        "path": path,
        "kind": "text",
        "content": content,
        "size": size,
        "mtime": mtime,
        "truncated": truncated,
    }


@router.put("/projects/{project_id}/file")
def write_file(project_id: str, req: WriteFileRequest) -> dict[str, Any]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, req.path, "write")
    if any(part in HIDDEN_PARTS for part in target.relative_to(root.resolve()).parts):
        raise HTTPException(status_code=400, detail="该路径不允许写入")
    try:
        mtime = write_project_text(root, target, req.content, expected_mtime=req.expected_mtime)
    except FileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"ok": True, "mtime": mtime}


@router.post("/projects/{project_id}/fs/create")
def fs_create(project_id: str, req: FsCreateRequest) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, req.path, "write")
    _guard_visible(root, target)
    with project_lock(root):
        if target.exists():
            raise HTTPException(status_code=409, detail="目标已存在")
        if req.kind == "dir":
            target.mkdir(parents=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_project_text(root, target, "")
    return {"ok": True}


@router.post("/projects/{project_id}/fs/rename")
def fs_rename(project_id: str, req: FsRenameRequest) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    source = _resolve_workspace_file(root, req.path, "write")
    target = _resolve_workspace_file(root, req.new_path, "write")
    _guard_visible(root, source)
    _guard_visible(root, target)
    with project_lock(root):
        if not source.exists():
            raise HTTPException(status_code=404, detail="源文件不存在")
        if target.exists():
            raise HTTPException(status_code=409, detail="目标已存在")
        sources = list(source.rglob("*.md")) if source.is_dir() else [source]
        moved = (
            [(file, target / file.relative_to(source)) for file in sources]
            if source.is_dir()
            else [(source, target)]
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        for old_file, new_file in moved:
            refresh_source(root, old_file)
            refresh_source(root, new_file)
    return {"ok": True}


@router.delete("/projects/{project_id}/fs")
def fs_delete(project_id: str, path: str) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, path, "write")
    if target == root.resolve():
        raise HTTPException(status_code=400, detail="不能删除工作区根目录")
    _guard_visible(root, target)
    with project_lock(root):
        sources = list(target.rglob("*.md")) if target.is_dir() else [target]
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            raise HTTPException(status_code=404, detail="文件不存在")
        for source in sources:
            refresh_source(root, source)
    return {"ok": True}
