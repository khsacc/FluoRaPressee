from concurrent.futures import Future

from PyQt5.QtCore import QObject, QThread, QCoreApplication, pyqtSignal


class GuiBridge(QObject):
    """Marshals callables from a non-GUI thread onto the Qt GUI thread.

    Qt automatically queues cross-thread signal delivery, so emitting _invoke from
    any thread runs _run() on whichever thread this QObject lives on (the GUI
    thread, since it must be constructed there before QApplication.exec()).
    """

    _invoke = pyqtSignal(object, object)

    def __init__(self):
        super().__init__()
        self._invoke.connect(self._run)

    def _run(self, fn, future):
        try:
            result = fn()
        except Exception as e:
            future.set_exception(e)
        else:
            future.set_result(result)

    def call(self, fn, timeout=60):
        """Run fn() on the GUI thread and block the calling thread until it returns.

        Must be called from a non-GUI thread: fn() only runs once the GUI event
        loop processes the queued signal, so a GUI-thread caller would deadlock
        waiting on its own event loop.
        """
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() is app.thread():
            raise RuntimeError("GuiBridge.call() must not be called from the GUI thread (would deadlock).")

        future = Future()
        self._invoke.emit(fn, future)
        return future.result(timeout=timeout)
