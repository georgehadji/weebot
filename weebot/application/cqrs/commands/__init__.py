"""CQRS commands for skill edit, validation, and transfer.

Also re-exports the main CQRS commands from the sibling commands.py
module, which is shadowed by this sub-package.
"""
from weebot.application.cqrs.commands.trajectory_commands import (
    ScoreTrajectoryCommand,
    BuildOptimizationBatchCommand,
)
from weebot.application.cqrs.commands.skill_edit_commands import (
    ApplySkillEditsCommand,
)
from weebot.application.cqrs.commands.validation_commands import (
    ValidateSkillCommand,
)
from weebot.application.cqrs.commands.transfer_commands import (
    ValidateTransferCommand,
)

# Re-export base commands from the sibling commands.py module.
# The sub-package `commands/` shadows `commands.py` in Python's import
# resolution, so we use the full module path via the cqrs parent.
import importlib as _il

# Import the shadowed .py module explicity via file path
_COMMANDS_PY_PATH = __file__.rsplit("commands", 1)[0] + "commands.py"
_spec = _il.util.spec_from_file_location(
    "weebot.application.cqrs.commands_py_module", _COMMANDS_PY_PATH
)
_cmds = _il.util.module_from_spec(_spec)
_spec.loader.exec_module(_cmds)

ArchiveSessionCommand = _cmds.ArchiveSessionCommand
CancelSessionCommand = _cmds.CancelSessionCommand
CompactMemoryCommand = _cmds.CompactMemoryCommand
CreatePlanCommand = _cmds.CreatePlanCommand
ExecuteStepCommand = _cmds.ExecuteStepCommand
ProcessMessageCommand = _cmds.ProcessMessageCommand
SummarizeCommand = _cmds.SummarizeCommand
UpdatePlanCommand = _cmds.UpdatePlanCommand

__all__ = [
    "ScoreTrajectoryCommand",
    "BuildOptimizationBatchCommand",
    "ApplySkillEditsCommand",
    "ValidateSkillCommand",
    "ValidateTransferCommand",
    "ArchiveSessionCommand",
    "CancelSessionCommand",
    "CompactMemoryCommand",
    "CreatePlanCommand",
    "ExecuteStepCommand",
    "ProcessMessageCommand",
    "SummarizeCommand",
    "UpdatePlanCommand",
]
