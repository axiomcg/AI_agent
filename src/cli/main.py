from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from typing import Optional

from src.config import get_settings
from src.tasking import TaskEventType, TaskStatus, get_task_manager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Отправка задач автономному браузерному агенту",
    )
    parser.add_argument("task", type=str, help="Текст задачи, которую должен выполнить агент")
    parser.add_argument(
        "--context",
        type=str,
        default="",
        help="Дополнительный контекст или ограничения для агента",
    )
    return parser


async def run_cli(task_text: str, context: str | None = None) -> None:
    settings = get_settings()
    manager = get_task_manager()
    metadata = {"channel": "cli", "context": context or "", "requested_at": datetime.utcnow().isoformat()}
    task = await manager.submit_task(task_text, metadata=metadata)
    print(f"[+] Задача поставлена в очередь. ID: {task.task_id} ({task.short_id()})")

    async for event in manager.stream_events(task.task_id):
        timestamp = event.timestamp.strftime("%H:%M:%S")
        if event.event_type == TaskEventType.STATUS:
            status_text = event.status.value if event.status else ""
            print(f"[{timestamp}] статус → {status_text}: {event.message}")
            if event.status in TaskStatus.terminal_states():
                break
        else:
            level = event.level.upper()
            print(f"[{timestamp}] {level}: {event.message}")

    final = manager.get_task(task.task_id)
    if not final:
        print("[-] Задача не найдена в менеджере")
        return

    print(f"[*] Финальный статус: {final.status.value}")
    if final.result_summary:
        print(f"[*] Итог: {final.result_summary}")


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    asyncio.run(run_cli(args.task, args.context))


if __name__ == "__main__":
    main()
