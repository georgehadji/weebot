"""remotion_video: videos made from React code with Remotion, rendered locally.

Remotion (github.com/remotion-dev/remotion, Remotion License: free for
individuals and companies of up to 3 people) renders React compositions frame
by frame in headless Chrome. The agent writes the composition under
Output/remotion/<project>/src; a fixed Node script owned by Weebot
(weebot/tools/remotion_render.cjs) bundles and renders it.
"""

from __future__ import annotations

import json

import pytest

from weebot.tools import remotion_video as rv
from weebot.tools.remotion_video import RemotionVideoTool


class _Proc:
    def __init__(self, out: bytes = b'{"output": "x"}', err: bytes = b"", code: int = 0):
        self._out, self._err, self.returncode = out, err, code
        self.stdin_data: bytes | None = None

    async def communicate(self, input: bytes | None = None):
        self.stdin_data = input
        return self._out, self._err

    def kill(self) -> None:
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    host = tmp_path / "host"
    (host / "node_modules" / "@remotion" / "renderer").mkdir(parents=True)
    projects = tmp_path / "Output" / "remotion"
    monkeypatch.setattr(rv, "_projects_root", lambda: projects)
    monkeypatch.setattr(rv, "_host_dir", lambda config: host)
    monkeypatch.setattr(rv.shutil, "which", lambda name: "/bin/node" if name == "node" else None)
    calls: list[tuple] = []
    proc = {"value": _Proc()}

    async def _exec(*args, **kwargs):
        calls.append((args, kwargs))
        return proc["value"]

    monkeypatch.setattr("asyncio.create_subprocess_exec", _exec)
    return {"projects": projects, "host": host, "calls": calls, "proc": proc}


async def test_scaffold_writes_a_starter_project_the_agent_can_edit(env):
    result = await RemotionVideoTool().execute(action="scaffold", project="promo")
    assert not result.is_error, result.error
    src = env["projects"] / "promo" / "src"
    assert (src / "index.ts").is_file() and (src / "Root.tsx").is_file()
    assert "registerRoot" in (src / "index.ts").read_text(encoding="utf-8")
    assert "<Composition" in (src / "Root.tsx").read_text(encoding="utf-8")
    # A second scaffold never overwrites the agent's edits.
    (src / "Root.tsx").write_text("edited", encoding="utf-8")
    await RemotionVideoTool().execute(action="scaffold", project="promo")
    assert (src / "Root.tsx").read_text(encoding="utf-8") == "edited"


async def test_render_runs_the_fixed_script_with_node_and_a_json_request(env):
    tool = RemotionVideoTool()
    await tool.execute(action="scaffold", project="promo")
    result = await tool.execute(
        action="render", project="promo", composition="Main", props={"title": "Hi"}
    )
    assert not result.is_error, result.error
    args, kwargs = env["calls"][0]
    assert args[0] == "/bin/node" and args[1].endswith("remotion_render.cjs")
    assert len(args) == 2  # the request goes on stdin, not the command line
    request = json.loads(env["proc"]["value"].stdin_data)
    assert request["action"] == "render" and request["composition"] == "Main"
    assert request["props"] == {"title": "Hi"} and request["codec"] == "h264"
    assert request["output"].endswith("promo\\out\\Main.mp4") or request["output"].endswith(
        "promo/out/Main.mp4"
    )
    assert request["host"] == str(env["host"])
    assert "OPENROUTER_API_KEY" not in kwargs["env"]


async def test_still_renders_one_frame_as_png(env):
    tool = RemotionVideoTool()
    await tool.execute(action="scaffold", project="promo")
    await tool.execute(action="still", project="promo", composition="Main", frame=30)
    request = json.loads(env["proc"]["value"].stdin_data)
    assert request["action"] == "still" and request["frame"] == 30
    assert request["output"].endswith("Main-30.png")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "render", "project": "../../etc", "composition": "Main"},
        {"action": "render", "project": "C:/Users", "composition": "Main"},
        {"action": "render", "project": "promo", "composition": "Main; rm -rf"},
        {"action": "render", "project": "promo", "composition": "Main", "codec": "exe"},
        {"action": "render", "project": "missing", "composition": "Main"},
        {"action": "delete", "project": "promo"},
    ],
)
async def test_bad_names_codecs_and_actions_are_refused(env, kwargs):
    tool = RemotionVideoTool()
    await tool.execute(action="scaffold", project="promo")
    result = await tool.execute(**kwargs)
    assert result.is_error
    assert env["calls"] == []


async def test_a_failed_render_reports_the_error(env):
    tool = RemotionVideoTool()
    await tool.execute(action="scaffold", project="promo")
    env["proc"]["value"] = _Proc(out=b"", err=b"Error: Composition Main not found", code=1)
    result = await tool.execute(action="render", project="promo", composition="Main")
    assert result.is_error and "not found" in result.error


async def test_a_missing_install_says_how_to_install(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "_host_dir", lambda config: tmp_path / "nowhere")
    tool = RemotionVideoTool()
    await tool.execute(action="scaffold", project="promo")
    result = await tool.execute(action="render", project="promo", composition="Main")
    assert result.is_error and "REMOTION_HOST" in result.error


def test_the_render_script_ships_with_the_tool():
    script = rv._RENDER_SCRIPT.read_text(encoding="utf-8")
    assert "renderMedia" in script and "renderStill" in script and "process.stdin" in script


def test_the_registry_offers_it_where_video_gen_is():
    from weebot.tools.tool_registry import RoleBasedToolRegistry

    for role, tools in RoleBasedToolRegistry.DEFAULT_ROLE_MAPPINGS.items():
        if "video_gen" in tools:
            assert "remotion_video" in tools, role
    assert RoleBasedToolRegistry.build_tool_class_map().get("remotion_video") is RemotionVideoTool


def test_the_builtin_skill_says_when_to_use_it():
    from weebot.application.skills.skill_registry import SkillRegistry

    registry = SkillRegistry()
    registry.load_all()
    skill = registry.get("remotion-video")
    assert skill is not None
    assert "remotion_video" in skill.content and "video_gen" in skill.content
    assert "useCurrentFrame" in skill.content and "license" in skill.content.lower()
