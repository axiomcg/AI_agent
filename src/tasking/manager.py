from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional
import uuid

from src.config import get_settings, AppSettings

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def terminal_states(cls) -> List["TaskStatus"]:
        return [cls.COMPLETED, cls.FAILED, cls.CANCELLED]


class TaskEventType(str, Enum):
    LOG = "log"
    STATUS = "status"
    USER = "user"


@dataclass
class TaskEvent:
    timestamp: datetime
    message: str
    event_type: TaskEventType = TaskEventType.LOG
    level: str = "info"
    status: Optional[TaskStatus] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "event_type": self.event_type.value,
            "level": self.level,
            "status": self.status.value if self.status else None,
            "metadata": self.metadata,
        }


@dataclass
class TaskRecord:
    task_id: str
    instructions: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    events: List[TaskEvent] = field(default_factory=list)
    result_summary: Optional[str] = None
    pending_user_prompt: Optional[str] = None

    def short_id(self) -> str:
        return self.task_id.split("-")[0]

    def as_row(self) -> List[str]:
        return [
            self.short_id(),
            self.instructions[:80] + ("…" if len(self.instructions) > 80 else ""),
            self.status.value,
            self.created_at.strftime("%H:%M:%S"),
            self.updated_at.strftime("%H:%M:%S"),
        ]


class TaskContext:
    def __init__(self, manager: "TaskManager", task: TaskRecord):
        self.manager = manager
        self.task = task

    async def log(self, message: str, level: str = "info", metadata: Optional[Dict[str, Any]] = None) -> None:
        await self.manager._append_event(
            self.task.task_id,
            TaskEvent(timestamp=datetime.utcnow(), message=message, level=level, metadata=metadata or {}),
        )

    async def set_status(self, status: TaskStatus, message: Optional[str] = None) -> None:
        await self.manager._set_status(self.task.task_id, status, message)

    async def complete(self, summary: str) -> None:
        await self.manager._complete_task(self.task.task_id, summary)

    async def fail(self, error_message: str) -> None:
        await self.manager._fail_task(self.task.task_id, error_message)

    async def request_user_input(self, prompt: str) -> str:
        return await self.manager._request_user_input(self.task.task_id, prompt)


class TaskExecutor:
    async def execute(self, ctx: TaskContext) -> None:  # pragma: no cover - interface definition
        raise NotImplementedError


class NoOpTaskExecutor(TaskExecutor):
    async def execute(self, ctx: TaskContext) -> None:
        await ctx.log(
            "Исполнитель ещё не подключен. Задача помещена в очередь интерфейса. Подключите оркестратор на следующем этапе.",
            level="warning",
        )
        await ctx.complete("Интерфейс успешно получил задачу; выполнение агента будет доступно после подключения оркестратора.")


class TaskManager:
    def __init__(self, settings: Optional[AppSettings] = None, executor: Optional[TaskExecutor] = None):
        self.settings = settings or get_settings()
        self.executor = executor or NoOpTaskExecutor()
        self.tasks: Dict[str, TaskRecord] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._event_subscribers: Dict[str, List[asyncio.Queue[TaskEvent]]] = {}
        self._user_waiters: Dict[str, asyncio.Future[str]] = {}
        self._lock = asyncio.Lock()
        self._worker: Optional[asyncio.Task[None]] = None

    async def submit_task(self, instructions: str, metadata: Optional[Dict[str, Any]] = None) -> TaskRecord:
        if not instructions.strip():
            raise ValueError("Задача должна содержать текст инструкции")

        task_id = str(uuid.uuid4())
        task = TaskRecord(task_id=task_id, instructions=instructions.strip(), metadata=metadata or {})
        async with self._lock:
            self.tasks[task_id] = task
        await self._append_event(
            task_id,
            TaskEvent(timestamp=datetime.utcnow(), message="Задача добавлена в очередь", event_type=TaskEventType.STATUS,
                      status=TaskStatus.QUEUED),
        )
        await self._queue.put(task_id)
        await self._ensure_worker()
        return task

    def list_tasks(self) -> List[TaskRecord]:
        return list(self.tasks.values())

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self.tasks.get(task_id)

    async def stream_events(self, task_id: str) -> AsyncIterator[TaskEvent]:
        task = self.get_task(task_id)
        if not task:
            return
        for event in task.events:
            yield event

        queue: asyncio.Queue[TaskEvent] = asyncio.Queue()
        self._event_subscribers.setdefault(task_id, []).append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            subscribers = self._event_subscribers.get(task_id, [])
            if queue in subscribers:
                subscribers.remove(queue)

    async def provide_user_input(self, task_id: str, response: str) -> None:
        response = response.strip()
        if not response:
            raise ValueError("Ответ не может быть пустым")
        waiter = self._user_waiters.get(task_id)
        if waiter and not waiter.done():
            waiter.set_result(response)
        await self._clear_user_prompt(task_id)
        await self._append_event(
            task_id,
            TaskEvent(
                timestamp=datetime.utcnow(),
                message=f"Ответ пользователя принят: {response}",
                event_type=TaskEventType.USER,
                level="info",
            ),
        )
        await self._set_status(task_id, TaskStatus.RUNNING, "Получен ответ пользователя")

    async def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            loop = asyncio.get_running_loop()
            self._worker = loop.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            task_id = await self._queue.get()
            task = self.get_task(task_id)
            if not task:
                self._queue.task_done()
                continue
            await self._set_status(task_id, TaskStatus.RUNNING)
            ctx = TaskContext(self, task)
            try:
                await self.executor.execute(ctx)
            except asyncio.CancelledError:
                await self._set_status(task_id, TaskStatus.CANCELLED, "Задача отменена")
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.exception("Ошибка при выполнении задачи %s", task_id)
                await ctx.fail(str(exc))
            finally:
                self._queue.task_done()

    async def _append_event(self, task_id: str, event: TaskEvent) -> None:
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task.events.append(event)
            task.updated_at = datetime.utcnow()
        queues = self._event_subscribers.get(task_id, [])
        for queue in queues:
            queue.put_nowait(event)

    async def _set_status(self, task_id: str, status: TaskStatus, message: Optional[str] = None) -> None:
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task.status = status
            task.updated_at = datetime.utcnow()
        await self._append_event(
            task_id,
            TaskEvent(
                timestamp=datetime.utcnow(),
                message=message or f"Статус обновлён: {status.value}",
                event_type=TaskEventType.STATUS,
                status=status,
            ),
        )

    async def _complete_task(self, task_id: str, summary: str) -> None:
        async with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.result_summary = summary
        await self._set_status(task_id, TaskStatus.COMPLETED, summary)

    async def _fail_task(self, task_id: str, error_message: str) -> None:
        await self._set_status(task_id, TaskStatus.FAILED, error_message)

    async def _request_user_input(self, task_id: str, prompt: str) -> str:
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._user_waiters[task_id] = waiter
        async with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.pending_user_prompt = prompt
        await self._set_status(task_id, TaskStatus.WAITING_USER, prompt)
        await self._append_event(
            task_id,
            TaskEvent(
                timestamp=datetime.utcnow(),
                message=f"Агент запросил ввод: {prompt}",
                event_type=TaskEventType.USER,
                level="warning",
            ),
        )
        response = await waiter
        await self._clear_user_prompt(task_id)
        return response

    async def _clear_user_prompt(self, task_id: str) -> None:
        async with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.pending_user_prompt = None
        self._user_waiters.pop(task_id, None)


_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _manager
    if _manager is None:
        from src.agent.orchestrator import AutonomousTaskExecutor

        _manager = TaskManager(executor=AutonomousTaskExecutor())
    return _manager
