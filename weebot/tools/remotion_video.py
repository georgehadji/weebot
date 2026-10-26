"""remotion_video -- make videos from React code with Remotion, rendered locally.

Remotion (github.com/remotion-dev/remotion) draws each frame of a React
component in headless Chrome and encodes the frames with ffmpeg. It suits
videos built from text, shapes, data, images and audio: explainers, title
cards, charts, captions, slideshows. For generated footage use ``video_gen``.

License: the Remotion License is free for individuals, non-profits and
for-profit companies of up to 3 people; larger companies need a company
license (remotion.pro).

How it runs:
- Projects live in ``Output/remotion/<project>/`` with the entry point at
  ``src/index.ts``. ``scaffold`` writes a starter the agent then edits with
  ``file_editor``.
- Remotion itself is installed once in a host folder (``REMOTION_HOST``, else
  ``~/.weebot-remotion``). The fixed script ``remotion_render.cjs`` next to this
  file bundles the project with webpack and renders it. The request goes to
  that script as JSON on stdin; node runs with an argument list, no shell, and
  without Weebot's API keys in its environment.
- The composition's code runs in headless Chrome, not in Node.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, ClassVar
from weebot.domain.models.output_trust import OutputTrust

from pydantic import PrivateAttr

from weebot.config.tool_config import ToolConfig, resolve_setting
from weebot.core.output_path import output_path
from weebot.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_RENDER_SCRIPT = Path(__file__).with_name("remotion_render.cjs")
_ACTIONS = ("scaffold", "compositions", "still", "render")
_CODECS = {"h264": "mp4", "h265": "mp4", "vp8": "webm", "vp9": "webm", "prores": "mov",
           "gif": "gif"}
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")
_COMPOSITION_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_TIMEOUT_S = 900
_MAX_LOG_CHARS = 4_000
_ENV_KEYS = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "PROGRAMFILES",
)

_INDEX_TS = """import {registerRoot} from 'remotion';
import {RemotionRoot} from './Root';

registerRoot(RemotionRoot);
"""
_ROOT_TSX = """import {Composition} from 'remotion';
import {Main} from './Main';

// One <Composition> per video. Durations are in frames: 150 frames at 30 fps = 5 s.
export const RemotionRoot: React.FC = () => (
  <Composition
    id="Main"
    component={Main}
    durationInFrames={150}
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{title: 'Hello from Weebot'}}
  />
);
"""
_MAIN_TSX = """import {
  AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig,
} from 'remotion';

export const Main: React.FC<{title: string}> = ({title}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const scale = spring({frame, fps, config: {damping: 200}});
  const opacity = interpolate(frame, [0, 20], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: '#0b1020', justifyContent: 'center',
      alignItems: 'center'}}>
      <h1 style={{color: 'white', fontSize: 120, fontFamily: 'sans-serif', opacity,
        transform: `scale(${scale})`}}>
        {title}
      </h1>
    </AbsoluteFill>
  );
};
"""


class _RemotionError(Exception):
    pass


def _projects_root() -> Path:
    return Path(output_path("Output/remotion"))


def _host_dir(config: ToolConfig | None) -> Path:
    configured = resolve_setting(config, "remotion_host", "REMOTION_HOST")
    return Path(configured) if configured else Path.home() / ".weebot-remotion"


def _child_env() -> dict[str, str]:
    return {k: v for k in _ENV_KEYS if (v := os.environ.get(k)) is not None}


class RemotionVideoTool(BaseTool):
    """Scaffold, preview and render Remotion (React) video projects."""

    output_trust: ClassVar[OutputTrust] = OutputTrust.LOCAL

    name: str = "remotion_video"
    description: str = (
        "Make a video from React code with Remotion: motion graphics, explainers, title "
        "cards, animated charts, captions, slideshows. Not for realistic generated footage "
        "(use video_gen). Actions: scaffold(project) writes Output/remotion/<project>/src "
        "(index.ts, Root.tsx, Main.tsx) for you to edit with file_editor; "
        "compositions(project) lists composition ids and sizes; still(project, composition, "
        "frame) renders one PNG to check the look; render(project, composition, props, codec) "
        "writes Output/remotion/<project>/out/<composition>.<ext>. Codecs: "
        + ", ".join(_CODECS)
        + " (default h264). Rendering can take minutes."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "project": {"type": "string", "description": "Project name: a-z, 0-9, - and _"},
            "composition": {"type": "string", "description": "Composition id, e.g. Main"},
            "props": {"type": "object", "description": "Input props passed to the composition"},
            "codec": {"type": "string", "enum": list(_CODECS)},
            "frame": {"type": "integer", "description": "Frame number for still"},
        },
        "required": ["action", "project"],
    }
    default_timeout_seconds: int = _TIMEOUT_S + 30

    _tool_config: ToolConfig | None = PrivateAttr(default=None)

    def set_config(self, config: ToolConfig) -> None:
        self._tool_config = config

    async def execute(self, action: str = "", **kwargs: Any) -> ToolResult:
        try:
            return ToolResult(output=await self._run(action, kwargs))
        except _RemotionError as exc:
            return ToolResult(output="", error=str(exc))

    async def _run(self, action: str, kw: dict[str, Any]) -> str:
        if action not in _ACTIONS:
            raise _RemotionError(f"action must be one of {', '.join(_ACTIONS)}")
        project = str(kw.get("project") or "")
        if not _PROJECT_RE.match(project):
            raise _RemotionError("project must be a short name: a-z, 0-9, - and _")
        root = _projects_root() / project
        if action == "scaffold":
            return await asyncio.to_thread(self._scaffold, root)

        entry = root / "src" / "index.ts"
        if not entry.is_file():
            raise _RemotionError(f"{entry} not found; run scaffold first")
        request: dict[str, Any] = {"action": action, "entry": str(entry),
                                   "props": kw.get("props") or {}}
        if action in ("still", "render"):
            composition = str(kw.get("composition") or "")
            if not _COMPOSITION_RE.match(composition):
                raise _RemotionError("composition must be an id like Main (a-z, 0-9 and -)")
            request["composition"] = composition
            out = root / "out"
            if action == "still":
                frame = int(kw.get("frame") or 0)
                request.update(frame=frame, output=str(out / f"{composition}-{frame}.png"))
            else:
                codec = str(kw.get("codec") or "h264")
                if codec not in _CODECS:
                    raise _RemotionError(f"codec must be one of {', '.join(_CODECS)}")
                request.update(codec=codec, output=str(out / f"{composition}.{_CODECS[codec]}"))
        return await self._render(request)

    @staticmethod
    def _scaffold(root: Path) -> str:
        src = root / "src"
        src.mkdir(parents=True, exist_ok=True)
        (root / "public").mkdir(exist_ok=True)
        written = []
        for name, text in (("index.ts", _INDEX_TS), ("Root.tsx", _ROOT_TSX),
                           ("Main.tsx", _MAIN_TSX)):
            path = src / name
            if not path.exists():
                path.write_text(text, encoding="utf-8")
                written.append(name)
        return (
            f"Project: {root}\nWrote: {', '.join(written) or 'nothing (files exist)'}\n"
            "Edit src/Main.tsx and src/Root.tsx with file_editor. Put images and audio in "
            "public/ and load them with staticFile('name.png'). Then still, then render."
        )

    async def _render(self, request: dict[str, Any]) -> str:
        host, node = _host_dir(self._tool_config), shutil.which("node")
        if node is None or not (host / "node_modules" / "@remotion" / "renderer").is_dir():
            raise _RemotionError(
                "Remotion is not installed. In ~/.weebot-remotion run `npm install remotion "
                "@remotion/bundler @remotion/renderer react react-dom`, or set REMOTION_HOST "
                "to such a folder; node must be on PATH."
            )
        request["host"] = str(host)
        if "output" in request:
            await asyncio.to_thread(Path(request["output"]).parent.mkdir, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            node, str(_RENDER_SCRIPT), cwd=str(host), env=_child_env(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(json.dumps(request).encode("utf-8")), timeout=_TIMEOUT_S
            )
        except TimeoutError:
            proc.kill()
            logger.warning("remotion %s timed out", request["action"])
            raise _RemotionError(
                f"remotion {request['action']} timed out after {_TIMEOUT_S} s"
            ) from None
        if proc.returncode != 0:
            detail = err.decode("utf-8", errors="replace").strip()[-_MAX_LOG_CHARS:]
            raise _RemotionError(f"remotion {request['action']} failed: {detail}")
        return out.decode("utf-8", errors="replace")[-_MAX_LOG_CHARS:]

    async def health_check(self) -> bool:
        host = _host_dir(self._tool_config)
        return shutil.which("node") is not None and (host / "node_modules" / "remotion").is_dir()
