from __future__ import annotations

from pathlib import Path

from scanner import (
    bytes_to_human,
    delete_files,
    deletion_mode,
    duplicate_candidates_for_delete,
    find_duplicates,
    folder_summary,
    largest_files,
    old_files,
    scan_files,
    summarize_by_extension,
    trash_backend,
)


def ask_folder() -> Path:
    while True:
        raw = input("Путь к папке для анализа (Enter = текущая): ").strip()
        target = Path(raw).expanduser() if raw else Path.cwd()
        if target.exists() and target.is_dir():
            return target
        print("Папка не найдена или это не директория. Попробуйте снова.")


def ask_int(prompt: str, default: int, min_value: int = 1) -> int:
    while True:
        raw = input(f"{prompt} [по умолчанию {default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Введите целое число.")
            continue

        if value < min_value:
            print(f"Число должно быть >= {min_value}.")
            continue

        return value


def print_file_list(title: str, files, limit: int = 10) -> None:
    print(f"\n{title}")
    if not files:
        print("  (нет данных)")
        return

    for idx, file_info in enumerate(files[:limit], 1):
        print(
            f"  {idx:>2}. {bytes_to_human(file_info.size):>10} | "
            f"{file_info.modified:%Y-%m-%d %H:%M} | {file_info.path}"
        )


def print_extension_summary(summary: dict[str, dict[str, int]], limit: int = 10) -> None:
    print("\nТипы файлов (по суммарному размеру):")
    if not summary:
        print("  (нет данных)")
        return

    ordered = sorted(summary.items(), key=lambda item: item[1]["total_size"], reverse=True)
    for idx, (ext, meta) in enumerate(ordered[:limit], 1):
        print(
            f"  {idx:>2}. {ext:<10} | {meta['count']:>5} шт | "
            f"{bytes_to_human(meta['total_size'])}"
        )


def confirm_delete(targets_count: int, bytes_total: int) -> bool:
    mode = deletion_mode()
    if mode == "trash":
        warning = f"Файлы будут перемещены в корзину (backend: {trash_backend()})."
    else:
        warning = "Внимание: удаление выполняется БЕЗВОЗВРАТНО."

    print(
        f"\n{warning} "
        f"Будет удалено: {targets_count} файлов ({bytes_to_human(bytes_total)})."
    )
    token = input('Для подтверждения введите "DELETE": ').strip()
    return token == "DELETE"


def recompute(root: Path, old_days: int):
    files = scan_files(root)
    old = old_files(files, days=old_days)
    dups = find_duplicates(files)
    dup_candidates = duplicate_candidates_for_delete(dups, keep="newest")
    return files, old, dups, dup_candidates


def main() -> None:
    # БЛОК СТАРТА И БАЗОВОГО СКАНИРОВАНИЯ ||
    #                                      ||
    #                                      \/
    print("Folder Scanner MVP")
    root = ask_folder()
    old_days = ask_int("Считать файл старым через сколько дней", default=90)

    files, old, duplicates, dup_candidates = recompute(root, old_days)
    summary = folder_summary(files)

    print("\n--- Сводка ---")
    print(f"Папка: {root}")
    print(f"Файлов найдено: {summary['total_files']}")
    print(f"Общий размер: {bytes_to_human(summary['total_size'])}")

    print_file_list("Топ-10 самых больших файлов:", largest_files(files, limit=10), limit=10)
    print_file_list(f"Топ-10 самых старых файлов (старше {old_days} дней):", old, limit=10)
    print_extension_summary(summarize_by_extension(files), limit=10)

    potential_saving = sum(item.size for item in dup_candidates)
    print("\n--- Дубликаты ---")
    print(f"Групп дубликатов: {len(duplicates)}")
    print(f"Кандидатов на удаление (оставляя по 1 копии): {len(dup_candidates)}")
    print(f"Потенциально освободится: {bytes_to_human(potential_saving)}")

    # БЛОК ДЕЙСТВИЙ (MVP) ||
    #                     ||
    #                     \/
    while True:
        print("\nВыберите действие:")
        print("  1 - Удалить N самых старых файлов")
        print("  2 - Удалить дубликаты (оставить самый новый файл в каждой группе)")
        print("  0 - Выход")
        action = input("Ваш выбор: ").strip()

        if action == "0":
            print("Завершено.")
            return

        if action == "1":
            if not old:
                print("Старых файлов для удаления нет.")
                continue

            count = ask_int("Сколько старых файлов удалить", default=min(10, len(old)))
            targets = old[:count]
            print_file_list("Будут удалены:", targets, limit=len(targets))

            if not confirm_delete(len(targets), sum(f.size for f in targets)):
                print("Удаление отменено.")
                continue

            deleted, errors = delete_files([f.path for f in targets])
            print(f"Удалено файлов: {deleted}")
            if errors:
                print("Ошибки при удалении:")
                for path, err in errors[:5]:
                    print(f"  - {path}: {err}")

            files, old, duplicates, dup_candidates = recompute(root, old_days)
            continue

        if action == "2":
            if not dup_candidates:
                print("Кандидатов на удаление среди дубликатов нет.")
                continue

            count = ask_int(
                "Сколько файлов-дубликатов удалить",
                default=len(dup_candidates),
            )
            targets = dup_candidates[:count]
            print_file_list("Будут удалены дубликаты:", targets, limit=min(len(targets), 20))

            if not confirm_delete(len(targets), sum(f.size for f in targets)):
                print("Удаление отменено.")
                continue

            deleted, errors = delete_files([f.path for f in targets])
            print(f"Удалено файлов: {deleted}")
            if errors:
                print("Ошибки при удалении:")
                for path, err in errors[:5]:
                    print(f"  - {path}: {err}")

            files, old, duplicates, dup_candidates = recompute(root, old_days)
            continue

        print("Неизвестная команда.")


if __name__ == "__main__":
    main()
