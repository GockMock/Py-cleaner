from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib
import shutil
import subprocess

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None


@dataclass
class FileInfo:
    path: Path
    size: int
    modified: datetime
    extension: str


def scan_files(root: Path, recursive: bool = True) -> list[FileInfo]:
    """Сканировать папку и вернуть список файлов c метаданными."""
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Folder does not exist or is not a directory: {root}")

    result: list[FileInfo] = []
    iterator = root.rglob("*") if recursive else root.iterdir()

    for p in iterator:
        if not p.is_file():
            continue

        try:
            stat = p.stat()
        except OSError:
            # Файл мог исчезнуть/быть недоступен в процессе обхода
            continue

        result.append(
            FileInfo(
                path=p,
                size=stat.st_size,
                modified=datetime.fromtimestamp(stat.st_mtime),
                extension=p.suffix.lower() or "[no ext]",
            )
        )

    return result


def largest_files(files: list[FileInfo], limit: int = 10) -> list[FileInfo]:  # Найти большие
    return sorted(files, key=lambda f: f.size, reverse=True)[:limit]  # файлы


def old_files(files: list[FileInfo], days: int = 90, limit: int | None = None) -> list[FileInfo]:  # Найти
    cutoff = datetime.now() - timedelta(days=days)  # старые
    result = [f for f in files if f.modified < cutoff]  # файлы
    result.sort(key=lambda f: f.modified)
    if limit is not None:
        return result[:limit]
    return result


def summarize_by_extension(files: list[FileInfo]) -> dict[str, dict[str, int]]:  # Сколько файлов
    groups: dict[str, list[FileInfo]] = defaultdict(list)  # каждого типа и
    for f in files:
        groups[f.extension].append(f)  # суммарный объем

    summary: dict[str, dict[str, int]] = {}
    for ext, ext_files in groups.items():
        summary[ext] = {
            "count": len(ext_files),
            "total_size": sum(file.size for file in ext_files),
        }

    return summary


# БЛОК ОТВЕЧАЮЩИЙ ЗА ПОИСК ДУБЛИКАТОВ ||
#                                     ||
#                                     \/

def group_by_size(files: list[FileInfo]) -> dict[int, list[FileInfo]]:  # кандидаты по размеру
    groups: dict[int, list[FileInfo]] = defaultdict(list)
    for f in files:
        groups[f.size].append(f)
    # Если размер разный, это точно не дубликаты
    return {size: fs for size, fs in groups.items() if len(fs) > 1}


def file_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:  # Для одинаковых по размеру
    h = hashlib.sha256()  # считаем SHA-256
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def find_duplicates(files: list[FileInfo]) -> dict[str, list[FileInfo]]:
    """Найти группы файлов с одинаковым содержимым."""
    size_groups = group_by_size(files)
    duplicates: dict[str, list[FileInfo]] = {}

    for group in size_groups.values():
        hash_groups: dict[str, list[FileInfo]] = defaultdict(list)
        for f in group:
            try:
                digest = file_hash(f.path)
            except OSError:
                continue
            hash_groups[digest].append(f)

        for digest, same_files in hash_groups.items():
            if len(same_files) > 1:
                duplicates[digest] = sorted(same_files, key=lambda item: item.modified)

    return duplicates


def duplicate_candidates_for_delete(
    duplicates: dict[str, list[FileInfo]], keep: str = "newest"
) -> list[FileInfo]:
    """Вернуть список дубликатов на удаление (по 1 копии в каждой группе остается)."""
    candidates: list[FileInfo] = []

    for same_files in duplicates.values():
        if len(same_files) < 2:
            continue

        if keep == "oldest":
            ordered = sorted(same_files, key=lambda item: item.modified)
        else:
            ordered = sorted(same_files, key=lambda item: item.modified, reverse=True)

        # Первый остается, остальные кандидаты на удаление
        candidates.extend(ordered[1:])

    return sorted(candidates, key=lambda item: item.size, reverse=True)


# БЛОК ОТВЕЧАЮЩИЙ ЗА СВОДКУ/УДАЛЕНИЕ ||
#                                    ||
#                                    \/

def bytes_to_human(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def folder_summary(files: list[FileInfo]) -> dict[str, int]:
    return {
        "total_files": len(files),
        "total_size": sum(f.size for f in files),
    }


def deletion_mode() -> str:
    if trash_backend() != "none":
        return "trash"
    return "permanent"


def trash_backend() -> str:
    if send2trash is not None:
        return "send2trash"
    if shutil.which("gio"):
        return "gio"
    return "none"


def _move_to_trash(path: Path) -> None:
    errors: list[str] = []

    if send2trash is not None:
        try:
            send2trash(str(path))
            return
        except OSError as exc:
            errors.append(f"send2trash: {exc}")

    if shutil.which("gio"):
        result = subprocess.run(
            ["gio", "trash", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return
        details = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        errors.append(f"gio trash: {details}")

    if errors:
        raise OSError(" | ".join(errors))
    raise OSError("No trash backend available")


def delete_files(paths: list[Path]) -> tuple[int, list[tuple[Path, str]]]:
    """Удалить файлы (в корзину, если есть send2trash; иначе безвозвратно)."""
    deleted = 0
    errors: list[tuple[Path, str]] = []
    mode = deletion_mode()

    for path in paths:
        if not path.exists():
            deleted += 1
            continue

        try:
            if mode == "trash":
                _move_to_trash(path)
            else:
                path.unlink(missing_ok=True)
            deleted += 1
        except OSError as exc:
            errors.append((path, str(exc)))

    return deleted, errors
