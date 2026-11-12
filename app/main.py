"""SubSync entry point (started by SubSync.exe)."""
import faulthandler
import multiprocessing
import os
import sys
import time
import traceback

LOG = None


T0 = time.perf_counter()


def step(msg):
    """One start-up step in logs\\app.log, with the seconds since Python started."""
    if LOG:
        LOG.write(f"{time.strftime('%H:%M:%S')} +{time.perf_counter() - T0:.2f}s {msg}\n")
        LOG.flush()


def _log_setup():
    global LOG
    from subsync import paths

    paths.setup_environment()
    LOG = open(os.path.join(paths.LOGS, "app.log"), "a", encoding="utf-8", buffering=1)
    LOG.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    # native crashes (access violations inside DLLs) get a stack trace in the log
    faulthandler.enable(file=LOG, all_threads=True)
    sys.stdout = sys.stderr = LOG
    step(f"python {sys.version.split()[0]} at {sys.executable}")
    step("C++ runtime: " + ", ".join(paths.preload_vc_runtime()))

    def hook(t, v, tb):
        LOG.write("".join(traceback.format_exception(t, v, tb)))
        LOG.flush()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.critical(None, "SubSync – unexpected error",
                                     f"{v}\n\nDetails were written to:\n{os.path.join(paths.LOGS, 'app.log')}")
        except Exception:
            pass

    sys.excepthook = hook


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _log_setup()
    step("loading window library")
    from subsync.gui import run

    step("starting window")
    code = 1
    try:
        code = run(step)
    finally:
        step(f"closed (code {code})")
        LOG.flush()
        # hard exit: no lingering threads or helper processes keep this alive
        os._exit(code or 0)
