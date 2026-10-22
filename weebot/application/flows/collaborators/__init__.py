"""Collaborator modules extracted from PlanActFlow for better separation of concerns."""

from weebot.application.flows.collaborators.model_selector import ModelSelector

# EventEmitter and FlowPersistence were extracted from PlanActFlow but never
# wired in; nothing constructed them. Deleted in ICM fix plan W5.3 (F28).
__all__ = ["ModelSelector"]
