"""CQRS handlers for skill edit, validation, and transfer.

Also re-exports the main CQRS handlers from the sibling handlers.py
module, which is shadowed by this sub-package.
"""
from weebot.application.cqrs.handlers.trajectory_handler import (
    ScoreTrajectoryHandler,
    BuildOptimizationBatchHandler,
)
from weebot.application.cqrs.handlers.skill_edit_handler import (
    ApplySkillEditsHandler,
)
from weebot.application.cqrs.handlers.validation_handler import (
    ValidateSkillHandler,
)
from weebot.application.cqrs.handlers.transfer_handler import (
    ValidateTransferHandler,
)

# Re-export base handlers from the sibling handlers.py module.
import importlib as _il
_HANDLERS_PY_PATH = __file__.rsplit("handlers", 1)[0] + "handlers.py"
_spec = _il.util.spec_from_file_location(
    "weebot.application.cqrs.handlers_py_module", _HANDLERS_PY_PATH
)
_hdl = _il.util.module_from_spec(_spec)
_spec.loader.exec_module(_hdl)

ArchiveSessionHandler = _hdl.ArchiveSessionHandler
CancelSessionHandler = _hdl.CancelSessionHandler
CompactMemoryHandler = _hdl.CompactMemoryHandler
CreatePlanHandler = _hdl.CreatePlanHandler
ExecuteStepHandler = _hdl.ExecuteStepHandler
GetSessionHandler = _hdl.GetSessionHandler
GetSessionStatusHandler = _hdl.GetSessionStatusHandler
ListSessionsHandler = _hdl.ListSessionsHandler
UpdatePlanHandler = _hdl.UpdatePlanHandler
register_default_handlers = _hdl.register_default_handlers
register_skillopt_handlers = _hdl.register_skillopt_handlers

__all__ = [
    "ScoreTrajectoryHandler",
    "BuildOptimizationBatchHandler",
    "ApplySkillEditsHandler",
    "ValidateSkillHandler",
    "ValidateTransferHandler",
    "register_skillopt_handlers",
    "ArchiveSessionHandler",
    "CancelSessionHandler",
    "CompactMemoryHandler",
    "CreatePlanHandler",
    "ExecuteStepHandler",
    "GetSessionHandler",
    "GetSessionStatusHandler",
    "ListSessionsHandler",
    "UpdatePlanHandler",
    "register_default_handlers",
]
