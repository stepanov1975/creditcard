"""Private import-time attribution for executed package source."""

from __future__ import annotations

import os
import sys
from types import CodeType, FrameType

_PACKAGE_NAME = __package__
_PACKAGE_DIRECTORY = os.path.realpath(os.path.dirname(__file__))
_PACKAGE_PATH_PREFIX = f"{_PACKAGE_DIRECTORY}{os.sep}"


def _package_initialization_code() -> CodeType:
    frame: FrameType | None = sys._getframe()
    while frame is not None:
        if frame.f_globals.get("__name__") == _PACKAGE_NAME:
            return frame.f_code
        frame = frame.f_back
    raise RuntimeError("package initialization frame unavailable")


_EXECUTED_PACKAGE_CODES: dict[str, set[CodeType]] = {
    os.path.realpath(os.path.join(_PACKAGE_DIRECTORY, "__init__.py")): {
        _package_initialization_code()
    },
    os.path.realpath(__file__): {sys._getframe().f_code},
}


def _record_package_execution(event: str, arguments: tuple[object, ...]) -> None:
    if event != "exec" or len(arguments) != 1:
        return
    code = arguments[0]
    if (
        not isinstance(code, CodeType)
        or code.co_name != "<module>"
        or code.co_filename.startswith("<")
    ):
        return
    try:
        source_path = os.path.realpath(code.co_filename)
    except (OSError, ValueError):
        return
    if not source_path.startswith(_PACKAGE_PATH_PREFIX) or not source_path.endswith(".py"):
        return
    _EXECUTED_PACKAGE_CODES.setdefault(source_path, set()).add(code)


sys.addaudithook(_record_package_execution)
