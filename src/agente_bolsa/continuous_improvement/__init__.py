"""Continuous improvement subsystem.

Keep the package import light.  The resident orchestrator remains available
through the same public attribute, but is loaded only by callers that use it.
This lets read-only digest commands avoid constructing the resident runtime's
import graph before the digest handler starts.
"""

__all__ = ["ContinuousImprovementOrchestrator"]


def __getattr__(name: str):
    if name == "ContinuousImprovementOrchestrator":
        from .orchestrator import ContinuousImprovementOrchestrator

        return ContinuousImprovementOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
