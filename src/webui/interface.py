from __future__ import annotations

from collections import Counter
from typing import List, Optional

import gradio as gr
from gradio.themes import Base, Citrus, Default, Glass, Monochrome, Ocean, Origin, Soft

from src.config import get_settings
from src.tasking import get_task_manager, TaskRecord, TaskStatus


theme_map = {
    "Default": Default(),
    "Soft": Soft(),
    "Monochrome": Monochrome(),
    "Glass": Glass(),
    "Origin": Origin(),
    "Citrus": Citrus(),
    "Ocean": Ocean(),
    "Base": Base(),
}


def _format_task_table(tasks: List[TaskRecord]) -> List[List[str]]:
    return [task.as_row() for task in tasks]


def _format_queue_stats(tasks: List[TaskRecord]) -> str:
    if not tasks:
        return "The queue is empty. Submit a task to get started."
    counts = Counter(task.status for task in tasks)
    total = len(tasks)
    summary = [
        f"- Total tasks: **{total}**",
        f"- In progress: **{counts.get(TaskStatus.RUNNING, 0)}**",
        f"- Awaiting user input: **{counts.get(TaskStatus.WAITING_USER, 0)}**",
        f"- Completed: **{counts.get(TaskStatus.COMPLETED, 0)}**",
    ]
    return "\n".join(summary)


def _format_log(task_id: Optional[str]) -> str:
    manager = get_task_manager()
    if not task_id:
        return "Select a task to see its execution log."
    task = manager.get_task(task_id)
    if not task:
        return "Task not found in the manager."
    if not task.events:
        return "No events have been recorded yet."
    lines = []
    for event in task.events:
        ts = event.timestamp.strftime("%H:%M:%S")
        prefix = f"[{ts}] ({event.event_type.value})"
        suffix = f" - {event.message}"
        lines.append(f"{prefix}{suffix}")
    return "\n".join(lines)


def _format_active_task_info(task_id: Optional[str]) -> str:
    if not task_id:
        return "No active task."
    manager = get_task_manager()
    task = manager.get_task(task_id)
    if not task:
        return "Task not found."
    return (
        f"**Active task:** `{task.short_id()}` - {task.status.value}\n\n"
        f"**Instructions:** {task.instructions}"
    )


async def _handle_submit(instructions: str, current_task_id: str | None):
    manager = get_task_manager()
    metadata = {"channel": "webui"}

    try:
        task = await manager.submit_task(instructions, metadata=metadata)
    except ValueError as exc:
        return (
            f"Error: {exc}",
            gr.update(),
            gr.update(),
            gr.update(),
            current_task_id or "",
            gr.update(),
        )

    tasks = manager.list_tasks()
    selected_id = task.task_id
    dropdown = gr.update(choices=[t.task_id for t in tasks], value=selected_id)
    info_md = _format_active_task_info(selected_id)
    log_md = _format_log(selected_id)
    message = f"Task `{task.short_id()}` added to the queue. Watch the log on the right for updates."

    return (
        message,
        dropdown,
        info_md,
        log_md,
        selected_id,
        gr.update(value=""),
    )


def _refresh_dashboard(selected_task_id: str):
    manager = get_task_manager()
    tasks = manager.list_tasks()
    choices = [task.task_id for task in tasks]
    value = selected_task_id if selected_task_id in choices else (choices[0] if choices else None)
    dropdown = gr.update(choices=choices, value=value)
    info_md = _format_active_task_info(value)
    log_md = _format_log(value)
    return dropdown, info_md, log_md, (value or "")


def _handle_selection(task_id: str | None):
    task_id = task_id or ""
    return task_id, _format_active_task_info(task_id), _format_log(task_id)


def create_ui(theme_name: str = "Ocean"):
    settings = get_settings()
    css = """
    .header-text {
        text-align: center;
        margin-bottom: 20px;
    }
    .vnc-frame iframe {
        border: 1px solid #1f2933;
        border-radius: 8px;
        width: 100%;
        min-height: 320px;
    }
    """

    manager = get_task_manager()
    initial_tasks = manager.list_tasks()
    initial_choices = [t.task_id for t in initial_tasks]

    theme = theme_map.get(theme_name, theme_map["Ocean"])

    with gr.Blocks(title="Autonomous Browser Agent", theme=theme, css=css) as demo:
        selected_task_state = gr.State("")
        gr.Markdown(
            """
            # Autonomous Browser Agent
            **Submit a task and watch the live execution log.**
            """,
            elem_classes=["header-text"],
        )

        instructions = gr.Textbox(
            label="Task instructions",
            placeholder="Example: 'Read the latest 10 emails and remove spam'.",
            lines=5,
        )
        submit_btn = gr.Button("Run agent", variant="primary")
        submit_status = gr.Markdown("")

        with gr.Row():
            with gr.Column(scale=1):
                task_selector = gr.Dropdown(
                    label="Active tasks",
                    choices=initial_choices,
                    interactive=True,
                )
                active_info = gr.Markdown(_format_active_task_info(initial_choices[0] if initial_choices else None))
            with gr.Column(scale=2):
                gr.Markdown("### Execution log")
                log_panel = gr.Markdown("No log entries yet.")

        submit_btn.click(
            _handle_submit,
            inputs=[instructions, selected_task_state],
            outputs=[
                submit_status,
                task_selector,
                active_info,
                log_panel,
                selected_task_state,
                instructions,
            ],
        )

        task_selector.change(
            _handle_selection,
            inputs=[task_selector],
            outputs=[selected_task_state, active_info, log_panel],
        )

        gr.Timer(2.0).tick(
            _refresh_dashboard,
            inputs=[selected_task_state],
            outputs=[task_selector, active_info, log_panel, selected_task_state],
        )

    return demo
