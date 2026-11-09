"""文件树、文件读写与文件系统操作。"""

from __future__ import annotations

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
    _drop_index_source,
    _drop_kb_index,
    _guard_visible,
    _kb_path_parts,
    _rename_index_source,
    _require_project,
    _resolve_workspace_file,
    _sync_kb_index,
    _tree_node,
    base64,
    git_status_map,
    read_text,
    router,
    save_text,
    shutil,
    snapshot_file,
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
    if req.expected_mtime is not None and target.exists():
        current = int(target.stat().st_mtime * 1000)
        if abs(current - req.expected_mtime) > 2:
            raise HTTPException(status_code=409, detail="文件已被其他操作修改，请重新加载后再保存")
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file(root, target)
    save_text(target, req.content)
    return {"ok": True, "mtime": int(target.stat().st_mtime * 1000)}


@router.post("/projects/{project_id}/fs/create")
def fs_create(project_id: str, req: FsCreateRequest) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, req.path, "write")
    _guard_visible(root, target)
    if target.exists():
        raise HTTPException(status_code=409, detail="目标已存在")
    if req.kind == "dir":
        target.mkdir(parents=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        save_text(target, "")
    return {"ok": True}


@router.post("/projects/{project_id}/fs/rename")
def fs_rename(project_id: str, req: FsRenameRequest) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    source = _resolve_workspace_file(root, req.path, "write")
    target = _resolve_workspace_file(root, req.new_path, "write")
    _guard_visible(root, source)
    _guard_visible(root, target)
    if not source.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")
    if target.exists():
        raise HTTPException(status_code=409, detail="目标已存在")
    old_relative = source.relative_to(root.resolve()).as_posix()
    new_relative = target.relative_to(root.resolve()).as_posix()
    old_kb = _kb_path_parts(old_relative)
    new_kb = _kb_path_parts(new_relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    if old_kb:
        _drop_kb_index(root, old_kb[0], old_kb[1])
        if new_kb:
            _sync_kb_index(root, new_kb[0], new_kb[1])
    elif source.suffix.lower() == ".md":
        _rename_index_source(root, old_relative, new_relative)
    return {"ok": True}


@router.delete("/projects/{project_id}/fs")
def fs_delete(project_id: str, path: str) -> dict[str, bool]:
    project = _require_project(project_id)
    root = Path(project["path"])
    target = _resolve_workspace_file(root, path, "write")
    if target == root.resolve():
        raise HTTPException(status_code=400, detail="不能删除工作区根目录")
    _guard_visible(root, target)
    relative = target.relative_to(root.resolve()).as_posix()
    kb_parts = _kb_path_parts(relative)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    else:
        raise HTTPException(status_code=404, detail="文件不存在")
    if kb_parts:
        _drop_kb_index(root, kb_parts[0], kb_parts[1])
    else:
        # 删掉的章节也要退出索引，否则检索还在返回已经不存在的原文
        _drop_index_source(root, relative)
    return {"ok": True}
