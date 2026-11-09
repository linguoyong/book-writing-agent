"""通用文件工具和业务工具共用原子写入、冲突锁、审稿失效及索引更新。"""

from __future__ import annotations

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import DeleteResult, EditResult, WriteResult

from ..fileops import project_lock, write_project_text
from ..text import normalize_newlines, read_text


class ProjectFilesystemBackend(FilesystemBackend):
    def delete(self, file_path: str) -> DeleteResult:
        from ..fileops import check_write, refresh_source

        try:
            with project_lock(self.cwd):
                target = self._resolve_path(file_path)
                check_write(self.cwd, target)
                sources = list(target.rglob("*.md")) if target.is_dir() else [target]
                result = super().delete(file_path)
                if not result.error:
                    for source in sources:
                        refresh_source(self.cwd, source)
                return result
        except (OSError, ValueError, RuntimeError) as exc:
            return DeleteResult(error=f"删除失败：{exc}")

    def write(self, file_path: str, content: str) -> WriteResult:
        try:
            target = self._resolve_path(file_path)
            write_project_text(self.cwd, target, content)
            return WriteResult(path=file_path)
        except (OSError, ValueError, RuntimeError) as exc:
            return WriteResult(error=f"写入失败：{exc}")

    def edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        try:
            with project_lock(self.cwd):
                target = self._resolve_path(file_path)
                content = read_text(target)
                old = normalize_newlines(old_string)
                occurrences = content.count(old) if old else 0
                if not occurrences:
                    return EditResult(error="找不到待替换的文本")
                if occurrences > 1 and not replace_all:
                    return EditResult(
                        error="待替换文本出现多次，请提供更长的上下文或使用 replace_all"
                    )
                content = content.replace(
                    old, normalize_newlines(new_string), -1 if replace_all else 1
                )
                write_project_text(self.cwd, target, content)
                return EditResult(path=file_path, occurrences=occurrences if replace_all else 1)
        except (OSError, ValueError, RuntimeError) as exc:
            return EditResult(error=f"编辑失败：{exc}")
