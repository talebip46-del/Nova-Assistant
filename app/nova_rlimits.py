#!/usr/bin/env python3
# =====================================================================
#  Nova Code - resource limits for executed commands (v6.8)
#
#  "سقف CPU/RAM روی دستورهای اجراشده (نه فقط تایم‌اوت)":
#    POSIX   resource.setrlimit in Popen(preexec_fn=...):
#              RLIMIT_CPU   total CPU-seconds of the child tree
#              RLIMIT_AS    max virtual memory per process
#            + lower priority (nice) so the agent never starves the UI.
#    Windows Job Objects via ctypes:
#              JobObjectExtendedLimitInformation with
#                ProcessMemoryLimit  (RAM ceiling per process)
#                JobUserTimeLimit    (CPU seconds for the whole job)
#              + JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so the OS reaps
#              everything even if Nova dies.
#
#  Limits are opt-in per command via NOVA_CPU_LIMIT / NOVA_RAM_MB env
#  or /limit; 0 = off. Fail-soft: if setrlimit/Job objects are not
#  available the command still runs with the classic timeout watchdog.
# =====================================================================
import math
import os
import threading

DEFAULT_CPU_S = 0    # seconds of CPU time (0 = unlimited)
DEFAULT_RAM_MB = 0   # MB of RAM (0 = unlimited)


def parse_size(text):
    """'200m'/'2g'/'512000k'/'1024' -> MB. Bare numbers = MB. 0 on junk.
    v6.8.1: 'inf'/'1e999' (OverflowError on int()) are junk too - they
    used to CRASH Session.__init__ at boot via NOVA_RAM_LIMIT."""
    t = str(text or "").strip().lower()
    if not t:
        return 0
    mult = 1
    if t.endswith("k") or t.endswith("kb"):
        mult, t = 1 / 1024.0, t[:-2] if t.endswith("kb") else t[:-1]
    elif t.endswith("m") or t.endswith("mb"):
        mult, t = 1, (t[:-2] if t.endswith("mb") else t[:-1])
    elif t.endswith("g") or t.endswith("gb"):
        mult, t = 1024, (t[:-2] if t.endswith("gb") else t[:-1])
    try:
        f = float(t) * mult
        if not math.isfinite(f):
            return 0
        v = int(f)
        return v if v > 0 else 0
    except (ValueError, OverflowError):
        return 0


def env_limits():
    """NOVA_CPU_LIMIT (seconds) / NOVA_RAM_LIMIT (MB or with unit).
    v6.8.1: a hostile value like NOVA_CPU_LIMIT=inf must never crash
    the boot (int(float('inf')) raises OverflowError)."""
    try:
        f = float(os.environ.get("NOVA_CPU_LIMIT", "0") or 0)
        cpu = int(f) if math.isfinite(f) else 0
    except (ValueError, OverflowError):
        cpu = 0
    ram = parse_size(os.environ.get("NOVA_RAM_LIMIT", "0"))
    return {"cpu_s": max(0, cpu), "ram_mb": max(0, ram)}


# --------------------------------------------------------------- POSIX
def posix_preexec(cpu_s, ram_mb):
    """Build a preexec_fn that installs the rlimits in the child BEFORE
    exec (so even a runaway `import torch` hits the wall). Returns None
    when both limits are off or resource is unavailable."""
    if not cpu_s and not ram_mb:
        return None
    try:
        import resource
    except ImportError:
        return None

    def _apply():
        # v8.0: each limit gets its OWN try/except - one failing setrlimit
        # (e.g. RLIMIT_AS hard-capped lower inside a container) used to
        # silently skip the CPU cap AND nice as well, while the UI still
        # printed "CPU<=Ns, RAM<=NMB". Shortfalls are reported via
        # nova_log so the operator can see the fail-open.
        def _soft(tag, fn):
            try:
                fn()
            except Exception as e:
                try:
                    import nova_log
                    nova_log.soft("rlimits." + tag, e)
                except Exception:
                    pass
        if ram_mb:
            _soft("ram", lambda: resource.setrlimit(
                resource.RLIMIT_AS, (ram_mb * 1024 * 1024,) * 2))
        if cpu_s:
            _soft("cpu", lambda: resource.setrlimit(
                resource.RLIMIT_CPU, (cpu_s, cpu_s + 2)))
        _soft("nice", lambda: os.nice(5))
    return _apply


# --------------------------------------------------------------- Windows
class _WinJob:
    """Minimal Job Object wrapper: RAM + CPU caps, kill-on-close."""

    def __init__(self, job, job_time_s):
        self.job = job
        self.job_time_s = job_time_s

    def assign(self, pid):
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)  # ALL_ACCESS-ish
        if not h:
            return False
        try:
            ok = ctypes.windll.kernel32.AssignProcessToJobObject(self.job, h)
            return bool(ok)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)

    def close(self):
        import ctypes
        if self.job:
            ctypes.windll.kernel32.TerminateJobObject(self.job, 1)
            ctypes.windll.kernel32.CloseHandle(self.job)
            self.job = None


def windows_job(cpu_s, ram_mb):
    """Create a Windows Job Object with the given caps, or None."""
    if not cpu_s and not ram_mb:
        return None
    try:
        import ctypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ("ReadOperationCount", "WriteOperationCount",
                         "OtherOperationCount", "ReadTransferCount",
                         "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]

        JobObjectExtendedLimitInformation = 9
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
        JOB_OBJECT_LIMIT_JOB_TIME = 0x4
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        # NOTE: silent-breakaway is deliberately NOT granted - children
        # (build tools spawning compilers etc.) must stay inside the job.

        job = ctypes.windll.kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if ram_mb:
            info.ProcessMemoryLimit = ram_mb * 1024 * 1024
            info.JobMemoryLimit = ram_mb * 1024 * 1024
            flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
        if cpu_s:
            # 100ns units
            info.BasicLimitInformation.PerJobUserTimeLimit = int(cpu_s * 10_000_000)
            flags |= JOB_OBJECT_LIMIT_JOB_TIME
        info.BasicLimitInformation.LimitFlags = flags
        # v7.1.0: check the BOOL - on failure the job existed but had NO
        # caps while callers treated it as enforcing (silent fail-open).
        if not ctypes.windll.kernel32.SetInformationJobObject(
                job, JobObjectExtendedLimitInformation,
                ctypes.byref(info), ctypes.sizeof(info)):
            ctypes.windll.kernel32.CloseHandle(job)
            return None
        return _WinJob(job, cpu_s)
    except Exception:
        return None


# --------------------------------------------------------------- one-stop
def popen_kwargs(cpu_s=0, ram_mb=0):
    """kwargs for subprocess.Popen honouring the limits on this OS.
    Returns (kwargs, job_or_None). job must be .assign(pid)-ed after
    spawn and .close()d when done (Windows only).
    v8.0: preexec_fn is SKIPPED when the caller is multithreaded - the
    web /run path executes on ThreadingHTTPServer threads and Python
    documents that preexec_fn between fork and exec can DEADLOCK the
    child there (intermittent "command never starts"). The wall timeout
    still applies; the shortfall is announced via nova_log."""
    if os.name == "nt":
        job = windows_job(cpu_s, ram_mb)
        return ({}, job)
    fn = posix_preexec(cpu_s, ram_mb)
    if fn is None:
        return ({}, None)
    try:
        if threading.active_count() > 1:
            try:
                import nova_log
                nova_log.soft("rlimits.preexec_skipped",
                              RuntimeError("multithreaded caller"),
                              msg="rlimits not enforced via preexec_fn "
                                  "(fork+exec deadlock risk) - wall timeout "
                                  "still applies")
            except Exception:
                pass
            return ({}, None)
    except Exception:
        pass
    return ({"preexec_fn": fn}, None)
