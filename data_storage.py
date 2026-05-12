import os

from agents import function_tool

MANAGEABLE_STATUSES = {"registered", "pending", "stopped", "failed", "finished"}
MANAGEABLE_UPDATE_FIELDS = {"command", "conda_env", "cwd", "status", "problem"}


class TaskRegistry:
    def __init__(self):
        self.tasks: list[dict] = []
        self._next_task_id = 1

    def add(self, command: str, conda_env: str | None = None, cwd: str | None = None) -> dict:
        task = {
            "task_id": self._next_task_id,
            "command": command,
            "conda_env": conda_env,
            "cwd": cwd,
            "logdir": None,    
            "pid": None,      
            "status": "registered",
            "problem": None,
        }
        self.tasks.append(task)
        self._next_task_id += 1
        return task

    def update(self, task_id: int, **kwargs):
        for task in self.tasks:
            if task["task_id"] == task_id:
                task.update(kwargs)
                return
        raise KeyError(f"找不到任务: {task_id}")

    def running_tasks(self) -> list[dict]:
        self.refresh_statuses()
        return [
            task for task in self.tasks
            if task.get("status") == "running"
        ]

    def pending_tasks(self) -> list[dict]:
        self.refresh_statuses()
        return [
            task for task in self.tasks
            if task.get("status") == "pending"
        ]

    def stop_pending_tasks(self) -> list[dict]:
        self.refresh_statuses()
        stopped_tasks = []
        for task in self.tasks:
            if task.get("status") == "pending":
                task["status"] = "stopped"
                task["pid"] = None
                task["problem"] = "stopped by user"
                stopped_tasks.append(task)
        return stopped_tasks

    def manage_queue(
        self,
        action: str,
        task_ids: list[int] | None = None,
        status_filter: list[str] | None = None,
        updates: dict | None = None,
        before_task_id: int | None = None,
    ) -> dict:
        self.refresh_statuses()
        action = action.strip().lower()
        if action not in {"remove", "clear", "update", "reorder"}:
            return {"ok": False, "errors": [f"unsupported action: {action}"]}

        selected, errors = self._select_manageable_tasks(
            task_ids=task_ids,
            status_filter=status_filter,
            default_all=(action == "clear"),
            preserve_task_id_order=(action == "reorder" and bool(task_ids)),
        )
        if errors:
            return {"ok": False, "errors": errors}
        if not selected:
            return {"ok": False, "errors": ["no tasks matched"]}

        running = [task for task in selected if task.get("status") == "running"]
        if running:
            ids = ", ".join(str(task["task_id"]) for task in running)
            return {
                "ok": False,
                "errors": [f"running tasks cannot be managed directly: {ids}"],
            }

        if action in {"remove", "clear"}:
            selected_ids = {task["task_id"] for task in selected}
            self.tasks = [
                task for task in self.tasks
                if task["task_id"] not in selected_ids
            ]
            return {
                "ok": True,
                "action": action,
                "changed": selected,
                "message": f"removed {len(selected)} tasks",
            }

        if action == "update":
            normalized_updates, update_errors = self._normalize_updates(updates)
            if update_errors:
                return {"ok": False, "errors": update_errors}
            for task in selected:
                task.update(normalized_updates)
            return {
                "ok": True,
                "action": action,
                "changed": selected,
                "message": f"updated {len(selected)} tasks",
            }

        return self._reorder_tasks(selected, before_task_id)

    def next_pending_task(self) -> dict | None:
        pending = self.pending_tasks()
        if not pending:
            return None
        return pending[0]

    def activate_registered_tasks(self) -> int:
        self.refresh_statuses()
        count = 0
        for task in self.tasks:
            if task.get("status") == "registered":
                task["status"] = "pending"
                count += 1
        return count

    def refresh_statuses(self):
        for task in self.tasks:
            if task.get("status") != "running":
                continue

            pid = task.get("pid")
            if not self._pid_is_running(pid):
                task["status"] = "finished"
                continue

    def _pid_is_running(self, pid) -> bool:
        if pid is None:
            return False

        pid = int(pid)
        stat_path = f"/proc/{pid}/stat"
        if not os.path.exists(stat_path):
            return False

        with open(stat_path, "r", encoding="utf-8") as f:
            stat = f.read().split()
        return len(stat) > 2 and stat[2] != "Z"

    def _select_manageable_tasks(
        self,
        task_ids: list[int] | None,
        status_filter: list[str] | None,
        default_all: bool,
        preserve_task_id_order: bool,
    ) -> tuple[list[dict], list[str]]:
        errors = []
        selected = []
        selected_ids = set()

        if status_filter:
            invalid_statuses = [
                status for status in status_filter
                if status not in MANAGEABLE_STATUSES
            ]
            if invalid_statuses:
                errors.append(
                    "invalid status_filter: " + ", ".join(invalid_statuses)
                )

        task_by_id = {task["task_id"]: task for task in self.tasks}
        if task_ids:
            missing_ids = [
                task_id for task_id in task_ids
                if task_id not in task_by_id
            ]
            if missing_ids:
                errors.append(
                    "task_id not found: "
                    + ", ".join(str(task_id) for task_id in missing_ids)
                )
            ordered_ids = task_ids if preserve_task_id_order else [
                task["task_id"]
                for task in self.tasks
                if task["task_id"] in set(task_ids)
            ]
            for task_id in ordered_ids:
                task = task_by_id.get(task_id)
                if task is not None and task_id not in selected_ids:
                    selected.append(task)
                    selected_ids.add(task_id)

        if status_filter:
            filter_set = set(status_filter)
            for task in self.tasks:
                task_id = task["task_id"]
                if task_id not in selected_ids and task.get("status") in filter_set:
                    selected.append(task)
                    selected_ids.add(task_id)

        if not task_ids and not status_filter:
            if default_all:
                selected = [
                    task for task in self.tasks
                    if task.get("status") in MANAGEABLE_STATUSES
                ]
            else:
                errors.append("task_ids or status_filter is required")

        return selected, errors

    def _normalize_updates(self, updates: dict | None) -> tuple[dict, list[str]]:
        if not updates:
            return {}, ["updates is required"]

        invalid_fields = [
            field for field in updates
            if field not in MANAGEABLE_UPDATE_FIELDS
        ]
        if invalid_fields:
            return {}, [
                "unsupported update fields: " + ", ".join(invalid_fields)
            ]

        normalized = dict(updates)
        if "command" in normalized:
            command = str(normalized["command"]).strip()
            if not command:
                return {}, ["command cannot be empty"]
            normalized["command"] = command

        if "conda_env" in normalized and normalized["conda_env"] is not None:
            normalized["conda_env"] = str(normalized["conda_env"]).strip() or None

        if "cwd" in normalized and normalized["cwd"] is not None:
            cwd = str(normalized["cwd"]).strip()
            normalized["cwd"] = (
                os.path.abspath(os.path.expanduser(cwd))
                if cwd else None
            )

        if "status" in normalized:
            status = str(normalized["status"]).strip()
            if status not in MANAGEABLE_STATUSES:
                return {}, [f"invalid status update: {status}"]
            normalized["status"] = status

        return normalized, []

    def _reorder_tasks(self, selected: list[dict], before_task_id: int | None) -> dict:
        selected_ids = {task["task_id"] for task in selected}
        if before_task_id in selected_ids:
            return {
                "ok": False,
                "errors": ["before_task_id cannot be one of the moved tasks"],
            }

        remaining = [
            task for task in self.tasks
            if task["task_id"] not in selected_ids
        ]

        if before_task_id == 0:
            insert_index = 0
        elif before_task_id is None:
            insert_index = len(remaining)
        else:
            insert_index = next(
                (
                    index for index, task in enumerate(remaining)
                    if task["task_id"] == before_task_id
                ),
                None,
            )
            if insert_index is None:
                return {
                    "ok": False,
                    "errors": [f"before_task_id not found: {before_task_id}"],
                }

        self.tasks = remaining[:insert_index] + selected + remaining[insert_index:]
        return {
            "ok": True,
            "action": "reorder",
            "changed": selected,
            "message": f"reordered {len(selected)} tasks",
        }

    def to_context_str(self) -> str:
        self.refresh_statuses()
        if not self.tasks:
            return "暂无任务"

        lines = []
        for i, task in enumerate(self.tasks):
            line = (
                f"{i+1}. task_id={task['task_id']}, "
                f"command={task['command']}, "
                f"conda_env={task['conda_env']}, "
                f"cwd={task['cwd']}, "
                f"status={task['status']}, "
                f"pid={task['pid']}, "
                f"logdir={task['logdir']}"
            )
            if task.get("problem"):
                line += f", problem={task['problem']}"
            lines.append(line)
        return "\n".join(lines)

registry = TaskRegistry()

@function_tool
def register_task(command: str, conda_env: str | None = None, cwd: str | None = None) -> str:
    """记录一个新的训练任务"""
    command = command.strip()
    if not command:
        return "error: missing command"

    if conda_env is not None:
        conda_env = conda_env.strip() or None
    task_cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    task = registry.add(command=command, conda_env=conda_env, cwd=task_cwd)
    return (
        f"已记录任务 {task['task_id']}：{command}，"
        f"conda_env={conda_env}，cwd={task_cwd}，"
        f"当前共 {len(registry.tasks)} 个任务"
    )
