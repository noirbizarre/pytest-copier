from __future__ import annotations


class CopierError(RuntimeError):
    """Base class for error triggered by the copier fixture"""


class CopierTaskError(CopierError):
    """Triggered by post-generation tasks"""


class RunError(CopierError):
    """Triggered by a failed command"""
