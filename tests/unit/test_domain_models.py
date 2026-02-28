"""Unit tests for domain models: Task/Project and Message/Memory/AgentState."""
import pytest
from weebot.domain.models import (
    Task, Project, TaskStatus, ProjectStatus,
    Role, Message, Memory, AgentState, ToolCallSpec,
)


# ---------------------------------------------------------------------------
# Task / Project tests
# ---------------------------------------------------------------------------

def test_task_creation():
    task = Task(name="analyze", description="Analyze data", prompt="Analyze this dataset")
    assert task.name == "analyze"
    assert task.status == TaskStatus.PENDING


def test_project_add_task():
    project = Project(project_id="proj1", description="Test")
    task = Task(name="t1", description="d", prompt="p")
    project.add_task(task)
    assert len(project.tasks) == 1
    assert project.pending_count == 1


def test_project_completion():
    project = Project(project_id="proj1", description="Test")
    task = Task(name="t1", description="d", prompt="p")
    project.add_task(task)
    task.mark_complete("result")
    assert project.is_complete


def test_task_mark_failed():
    task = Task(name="t", description="d", prompt="p")
    task.mark_failed("something went wrong")
    assert task.status == TaskStatus.FAILED
    assert task.error == "something went wrong"
    assert task.completed_at is not None


def test_task_mark_running():
    task = Task(name="t", description="d", prompt="p")
    task.mark_running()
    assert task.status == TaskStatus.RUNNING
    assert task.started_at is not None


# ---------------------------------------------------------------------------
# Message / Memory / AgentState tests
# ---------------------------------------------------------------------------

def test_message_user():
    msg = Message(role=Role.USER, content="hello")
    assert msg.role == Role.USER
    d = msg.to_openai_dict()
    assert d["role"] == "user"
    assert d["content"] == "hello"


def test_message_tool():
    msg = Message(role=Role.TOOL, content="result", tool_call_id="call_abc")
    d = msg.to_openai_dict()
    assert d["role"] == "tool"
    assert d["tool_call_id"] == "call_abc"


def test_message_with_tool_calls():
    tc = ToolCallSpec(id="call_1", name="echo", arguments='{"text": "hi"}')
    msg = Message(role=Role.ASSISTANT, content="", tool_calls=[tc])
    d = msg.to_openai_dict()
    assert len(d["tool_calls"]) == 1
    assert d["tool_calls"][0]["function"]["name"] == "echo"


def test_message_system_classmethod():
    msg = Message.system("you are helpful")
    assert msg.role == Role.SYSTEM
    assert msg.content == "you are helpful"


def test_message_user_classmethod():
    msg = Message.user("hello")
    assert msg.role == Role.USER


def test_memory_add_and_limit():
    mem = Memory(max_messages=3)
    for i in range(5):
        mem.add(Message(role=Role.USER, content=str(i)))
    non_system = [m for m in mem.messages if m.role != Role.SYSTEM]
    assert len(non_system) <= 3


def test_memory_preserves_system_message():
    mem = Memory(max_messages=2)
    mem.add(Message.system("sys"))
    for i in range(5):
        mem.add(Message.user(str(i)))
    system_msgs = [m for m in mem.messages if m.role == Role.SYSTEM]
    assert len(system_msgs) == 1


def test_memory_to_openai_format():
    mem = Memory()
    mem.add(Message.system("sys"))
    mem.add(Message.user("hi"))
    fmt = mem.to_openai_format()
    assert fmt[0]["role"] == "system"
    assert fmt[1]["role"] == "user"


def test_memory_clear_keeps_system():
    mem = Memory()
    mem.add(Message.system("sys"))
    mem.add(Message.user("hi"))
    mem.clear()
    assert len(mem.messages) == 1
    assert mem.messages[0].role == Role.SYSTEM


def test_agent_state_values():
    assert AgentState.IDLE.value == "idle"
    assert AgentState.RUNNING.value == "running"
    assert AgentState.FINISHED.value == "finished"
    assert AgentState.ERROR.value == "error"
