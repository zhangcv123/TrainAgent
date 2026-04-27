import os

from agents import function_tool

class TaskRegistry:
    def __init__(self):
        self.tasks: list[dict] = []

    def add(self, file_path: str, conda_env: str):
        self.tasks.append({
            "file_path": file_path,
            "conda_env": conda_env,
            "logdir": None,    
            "pid": None,      
            "status": "registered",
            "problem": None,
        })

    def update(self, file_path: str, **kwargs):
        for task in self.tasks:
            if task["file_path"] == file_path:
                task.update(kwargs)
                return
        raise KeyError(f"找不到任务: {file_path}")

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

    def to_context_str(self) -> str:
        self.refresh_statuses()
        if not self.tasks:
            return "暂无任务"

        lines = []
        for i, task in enumerate(self.tasks):
            line = (
                f"{i+1}. file_path={task['file_path']}, "
                f"conda_env={task['conda_env']}, "
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
def register_task(file_path: str, conda_env: str) -> str:
    """记录一个新的训练任务"""
    registry.add(file_path=file_path, conda_env=conda_env)
    return f"已记录：{file_path} - {conda_env}，当前共 {len(registry.tasks)} 个任务"
