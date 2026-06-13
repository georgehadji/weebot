"""Composable termination conditions for agent flows."""
from weebot.application.termination.base import TerminationCondition, TerminationContext, TerminationResult
from weebot.application.termination.base import CompositeTermination
from weebot.application.termination.conditions import (
    MaxIterationTermination,
    TokenBudgetTermination,
    TextMentionTermination,
    WallClockTermination,
)
