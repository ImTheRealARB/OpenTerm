"""Memory cap for one strategy run inside a job worker (spec decision E).

Windows: the worker puts itself in a Job Object and sets a per-process committed-memory limit of "what it uses now
+ the cap" for the run, then lifts it. An allocation past the limit fails at once with MemoryError, so a runaway
strategy ends cleanly instead of paging the machine. Elsewhere: RLIMIT_AS the same way. The time limit is the job
runner's (it terminates the worker).
"""

from __future__ import annotations

import contextlib
import sys

_job = None  # Windows Job Object handle, created once per worker


class MemoryLimit(MemoryError):
    pass


def _win_set(limit_bytes: int | None) -> None:
    import ctypes
    from ctypes import wintypes

    global _job
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):  # noqa: N801 - Win32 names
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                     "OtherBytes")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    if _job is None:
        job = k32.CreateJobObjectW(None, None)
        if not job or not k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(k32.GetCurrentProcess())):
            raise OSError(ctypes.get_last_error(), "could not create the worker's job object")
        _job = job
    info = EXTENDED()
    if limit_bytes is not None:
        info.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = limit_bytes
    if not k32.SetInformationJobObject(wintypes.HANDLE(_job), 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "could not set the worker's memory limit")


@contextlib.contextmanager
def memory_cap(extra_mb: int):
    """Allows `extra_mb` more than the worker uses on entry; MemoryError past it is re-raised as MemoryLimit."""
    import psutil

    me = psutil.Process()
    if sys.platform == "win32":
        base = me.memory_info().private
        _win_set(base + extra_mb * 1024 * 1024)
        undo = lambda: _win_set(None)  # noqa: E731
    else:
        import resource

        old = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (me.memory_info().vms + extra_mb * 1024 * 1024, old[1]))
        undo = lambda: resource.setrlimit(resource.RLIMIT_AS, old)  # noqa: E731
    try:
        yield
    except MemoryError as e:
        raise MemoryLimit(f"MEMORY LIMIT: THE STRATEGY NEEDED MORE THAN {extra_mb} MB") from e
    finally:
        undo()
