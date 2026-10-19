"""Worker process main loop. One task at a time from `tasks`; progress and results go back on `results`.

Messages to the server: ("progress", job_id, fraction, msg) | ("done", job_id, result) | ("error", job_id, text)
| ("cancelled", job_id, None). `cancel` is a shared flag the server sets (and resets before it sends a task); `progress()` raises once it is set.
"""

from .kinds import KINDS, JobCancelled


def worker_main(tasks, results, cancel) -> None:
    while True:
        try:
            task = tasks.recv()
        except (EOFError, OSError):
            return
        if task is None:
            return
        job_id, kind, params = task

        def progress(fraction: float, msg: str = "", job_id=job_id) -> None:
            if cancel.value:
                raise JobCancelled
            results.send(("progress", job_id, float(fraction), str(msg)[:200]))

        try:
            out = KINDS[kind].fn(params, progress)
            results.send(("done", job_id, out))
        except JobCancelled:
            results.send(("cancelled", job_id, None))
        except Exception as e:  # noqa: BLE001 - any job failure is reported, the worker lives on
            results.send(("error", job_id, f"{type(e).__name__}: {e}"[:500]))
