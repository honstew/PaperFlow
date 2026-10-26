from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class FunctionThread(QThread):
    """Run a blocking callable in a QThread and deliver the result to the UI.

    A QThread object is used instead of QRunnable because QRunnable's C++
    lifetime ends as soon as run() returns, which can invalidate a separate
    signals QObject before the queued signal reaches the GUI thread.
    """

    result = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        parent: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.setObjectName(getattr(fn, "__name__", "background-task"))

    def run(self) -> None:
        try:
            value = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            logger.exception("Background task failed: %s", self.fn)
            self.error.emit(str(exc) or exc.__class__.__name__)
        else:
            self.result.emit(value)