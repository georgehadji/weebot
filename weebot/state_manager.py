#!/usr/bin/env python3
"""state_manager.py - Persistent Project State & Resume Capability

Λειτουργίες:
------------
1. Persistent αποθήκευση κατάστασης project (SQLite)
2. Checkpoint system για pause/resume
3. Automatic recovery από failures
4. History tracking (completed tasks, errors)
5. Context management για μεταβλητές μεταξύ tasks

Βασικές Έννοιες:
----------------
ProjectState: Η πλήρης κατάσταση ενός project
    - status: PENDING/RUNNING/PAUSED/COMPLETED/FAILED
    - completed_tasks: Λίστα ολοκληρωμένων tasks
    - current_task: Τρέχον task (αν running)
    - context: Dictionary με shared data
    - checkpoints: Λίστα από checkpoints

Οδηγίες Χρήσης:
---------------
1. Δημιουργία Project:
    sm = StateManager()
    state = sm.create_project("my_project", "Description")

2. Εκτέλεση με Resume Capability:
    async with ResumableTask(sm, "my_project", "task_name") as task:
        if task is None:  # Already completed
            return
        # Do work...

3. Recovery από Crash:
    state = sm.load_state("my_project")
    if state.status == ProjectStatus.RUNNING:
        # Resume from last completed task
        print(f"Resuming from task: {state.current_task}")
"""
import json
import pickle
import sqlite3
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime
import asyncio


class ProjectStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"  # Waiting for user input
    COMPLETED = "completed"
    FAILED = "failed"


ACTIVITY_KINDS = {
    "idle", "job", "exec", "read", "write", "edit",
    "search", "browser", "message", "tool",
}


@dataclass
class SubSession:
    session_id: str
    name: str
    activity_kind: str
    status: str = "running"     # running / completed / failed
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.started_at is None:
            self.started_at = datetime.now()


@dataclass
class Checkpoint:
    id: str
    timestamp: datetime
    description: str
    requires_input: bool
    input_prompt: Optional[str] = None
    resolved: bool = False
    user_response: Optional[str] = None


@dataclass
class ProjectState:
    project_id: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    current_task: Optional[str] = None
    completed_tasks: List[str] = None
    context: Dict[str, Any] = None
    checkpoints: List[Checkpoint] = None
    error_log: List[str] = None
    metadata: Dict[str, Any] = None
    sub_sessions: List[SubSession] = None

    def __post_init__(self) -> None:
        if self.completed_tasks is None:
            self.completed_tasks = []
        if self.context is None:
            self.context = {}
        if self.checkpoints is None:
            self.checkpoints = []
        if self.error_log is None:
            self.error_log = []
        if self.metadata is None:
            self.metadata = {}
        if self.sub_sessions is None:
            self.sub_sessions = []


class StateManager:
    """SQLite-based persistent state management"""
    
    def __init__(self, db_path: str = "projects.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    state BLOB,
                    updated_at TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    data BLOB,
                    created_at TIMESTAMP,
                    resolved BOOLEAN DEFAULT FALSE,
                    user_response TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                )
            """)

            # Product management — requirements backlog
            conn.execute("""
                CREATE TABLE IF NOT EXISTS requirements (
                    req_id     TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title      TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category   TEXT DEFAULT 'feature',
                    priority   INTEGER DEFAULT 3,
                    status     TEXT DEFAULT 'draft',
                    tags       TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Knowledge management — FTS5 full-text search notes
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_notes USING fts5(
                    note_id    UNINDEXED,
                    project_id UNINDEXED,
                    created_at UNINDEXED,
                    source     UNINDEXED,
                    title,
                    body,
                    tags
                )
            """)

            # Video ingestion — source tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS video_sources (
                    source_id   TEXT PRIMARY KEY,
                    project_id  TEXT NOT NULL,
                    url         TEXT NOT NULL,
                    title       TEXT DEFAULT '',
                    language    TEXT DEFAULT 'en',
                    chunk_count INTEGER DEFAULT 0,
                    status      TEXT DEFAULT 'done',
                    error_msg   TEXT DEFAULT '',
                    ingested_at TEXT NOT NULL
                )
            """)

            conn.commit()
    
    def create_project(self, project_id: str, description: str) -> ProjectState:
        """Create new project state"""
        now = datetime.now()
        state = ProjectState(
            project_id=project_id,
            status=ProjectStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata={"description": description}
        )
        self.save_state(state)
        return state
    
    def save_state(self, state: ProjectState) -> None:
        """Save project state to database."""
        state.updated_at = datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO projects (project_id, state, updated_at)
                VALUES (?, ?, ?)
                """,
                (state.project_id, pickle.dumps(state), state.updated_at)
            )
            conn.commit()
    
    def load_state(self, project_id: str) -> Optional[ProjectState]:
        """Load project state from database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT state FROM projects WHERE project_id = ?",
                (project_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return pickle.loads(row[0])
            return None
    
    def list_projects(self) -> List[Dict]:
        """List all projects"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT project_id, updated_at FROM projects ORDER BY updated_at DESC"
            )
            return [
                {"project_id": row[0], "updated_at": row[1]}
                for row in cursor.fetchall()
            ]
    
    def add_checkpoint(self, project_id: str, description: str,
                       input_prompt: Optional[str] = None) -> str:
        """Add checkpoint requiring user input"""
        checkpoint_id = f"chk_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        checkpoint = Checkpoint(
            id=checkpoint_id,
            timestamp=datetime.now(),
            description=description,
            requires_input=True,
            input_prompt=input_prompt
        )
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (checkpoint_id, project_id, data, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (checkpoint_id, project_id, pickle.dumps(checkpoint), checkpoint.timestamp)
            )
            conn.commit()
        
        return checkpoint_id
    
    def resolve_checkpoint(self, checkpoint_id: str, user_response: str) -> None:
        """Resolve checkpoint with user input."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE checkpoints
                SET resolved = TRUE, user_response = ?
                WHERE checkpoint_id = ?
                """,
                (user_response, checkpoint_id)
            )
            conn.commit()
    
    def start_sub_session(self, project_id: str, name: str,
                          activity_kind: str = "job") -> str:
        """Create and persist a new sub-session for a project."""
        state = self.load_state(project_id)
        if not state:
            raise ValueError(f"Project {project_id} not found")
        session_id = f"ss_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        state.sub_sessions.append(SubSession(
            session_id=session_id,
            name=name,
            activity_kind=activity_kind,
        ))
        self.save_state(state)
        return session_id

    def end_sub_session(self, project_id: str, name: str,
                        status: str = "completed") -> None:
        """Mark the most recent open sub-session with the given name as ended."""
        state = self.load_state(project_id)
        if not state:
            return
        for ss in state.sub_sessions:
            if ss.name == name and ss.ended_at is None:
                ss.ended_at = datetime.now()
                ss.status = status
                break
        self.save_state(state)

    def get_pending_checkpoints(self, project_id: str) -> List[Checkpoint]:
        """Get unresolved checkpoints for project"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT data FROM checkpoints
                WHERE project_id = ? AND resolved = FALSE
                ORDER BY created_at DESC
                """,
                (project_id,)
            )
            return [pickle.loads(row[0]) for row in cursor.fetchall()]


class ResumableTask:
    """Context manager για resumable task execution."""

    def __init__(self, state_manager: StateManager, project_id: str, task_name: str) -> None:
        self.sm = state_manager
        self.project_id = project_id
        self.task_name = task_name
        self.state = None
        self.checkpoint_id = None
    
    async def __aenter__(self) -> Optional["ResumableTask"]:
        """Enter task context."""
        self.state = self.sm.load_state(self.project_id)

        if not self.state:
            raise ValueError(f"Project {self.project_id} not found")

        # Check if already completed
        if self.task_name in self.state.completed_tasks:
            return None  # Skip execution

        # Update status
        self.state.status = ProjectStatus.RUNNING
        self.state.current_task = self.task_name
        self.sm.save_state(self.state)
        self.sm.start_sub_session(self.project_id, self.task_name, activity_kind="job")

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit task context.

        Uses try/finally to guarantee end_sub_session is always called, and
        isolates save_state() failures so they never mask the original exception.
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        status = "completed" if exc_type is None else "failed"
        try:
            if exc_type is None:
                # Success — mark task completed
                if self.task_name not in self.state.completed_tasks:
                    self.state.completed_tasks.append(self.task_name)
                self.state.current_task = None
            else:
                # Failure — record error, do not propagate save exceptions
                self.state.error_log.append(str(exc_val))
                self.state.status = ProjectStatus.FAILED
            self.sm.save_state(self.state)
        except Exception as save_err:
            # save_state() failed: log but do NOT re-raise.
            # Re-raising here would replace the original exc_val with save_err,
            # causing permanent RUNNING status stuck-state on restart.
            _log.critical(
                "ResumableTask.__aexit__: save_state failed for project=%s task=%s "
                "original_exc=%r save_err=%r — state may be inconsistent",
                self.project_id, self.task_name, exc_val, save_err,
            )
        finally:
            # Always close the sub-session, even if save_state raised.
            try:
                self.sm.end_sub_session(self.project_id, self.task_name, status=status)
            except Exception as sub_err:
                _log.warning(
                    "ResumableTask.__aexit__: end_sub_session failed: %r", sub_err
                )
    
    async def checkpoint(self, description: str, input_prompt: str) -> str:
        """Create checkpoint and wait for user input"""
        self.checkpoint_id = self.sm.add_checkpoint(
            self.project_id, description, input_prompt
        )
        
        self.state.status = ProjectStatus.PAUSED
        self.sm.save_state(self.state)
        
        return self.checkpoint_id
