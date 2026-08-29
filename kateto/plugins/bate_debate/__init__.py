"""Bate Debate de Bate de Chocolate — Autonomous multi-voice debate mode.

Implements pj tasks 046/048/050: courtroom debate with judge, objections,
and automatic registry logging.
"""

from .orchestrator import (
    DebateProvider,
    DebateRecord,
    run_debate,
)
from .mock import MockProvider

__all__ = [
    "DebateProvider",
    "DebateRecord",
    "run_debate",
    "MockProvider",
]