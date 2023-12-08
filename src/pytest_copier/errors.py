from __future__ import annotations


class CopierError(RuntimeError):
    """Base class for error triggered by the copier fixture"""


class CopierTaskError(CopierError):
    """Triggered by post-generation tasks"""


class ProjectRunError(CopierError):
    """Triggered by a command executed in th project"""
