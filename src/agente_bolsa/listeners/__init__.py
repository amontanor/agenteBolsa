"""CrewAI event listeners.

Importing this package registers listener instances when CrewAI is installed.
"""

try:
    from .agent_history_listener import agent_history_listener
except Exception:
    agent_history_listener = None

__all__ = ["agent_history_listener"]
