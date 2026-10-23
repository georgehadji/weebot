---
type: object
name: Media tools
code: ImageGenTool, VideoGenTool, VideoIngestTool, RemotionVideoTool, VoiceInputTool, VoiceOutputTool, YouTubeDownloadTool
cluster: tools
universe: live
status: verified
verified: 2026-10-23
commit: 2be1ab8a
---

# Media tools

Tools that make or ingest images, video and audio: `image_gen`, `video_gen`, `video_ingest`, `remotion_video`, `voice_input`, `voice_output`, and `youtube_download`.

## Why this shape
Each tool owns its backend and writes files under the workspace. Paid generation reads provider keys straight from the environment and falls back to a free path (SVG templates for images, `weebot/tools/image_gen_tool.py:586-619`). Tools whose backend is a port (`ToolRepositoryPort`, `SpeechPort`) refuse to construct without it (`video_ingest_tool.py:226-233`, `voice_input_tool.py:39-46`, `voice_output_tool.py:47-50`), and the registry supplies it from `wiring()["collaborators"]` (`application/di/_factories.py:453-455`).

## Shape

| Tool name | Class, file:line | Backend | Collaborator | Roles |
|---|---|---|---|---|
| `image_gen` | `ImageGenTool` `weebot/tools/image_gen_tool.py:255` | kinds `hero/card/icon/logo/testimonial` (SVG), `svg/ai` (Replicate if `REPLICATE_API_TOKEN`, else themed SVG), `openrouter` (OpenRouter, xAI or Ideogram direct, `IMAGE_CASCADE`) (`:877-923, 586-615`) | none | admin, webhook, coder, designer |
| `video_gen` | `VideoGenTool` `weebot/tools/video_gen_tool.py:51` | OpenRouter video models or xAI direct (`:104-146, 283-286`) | none | automation, admin, webhook, coder, designer |
| `video_ingest` | `VideoIngestTool` `weebot/tools/video_ingest_tool.py:171` | `youtube_transcript_api` + oEmbed; actions `ingest_youtube`, `list_sources`, `export_jsonl` (`:179-197`) | `repo: ToolRepositoryPort` | researcher, admin, webhook |
| `remotion_video` | `RemotionVideoTool` `weebot/tools/remotion_video.py:117` | `node remotion_render.cjs` in `REMOTION_HOST` or `~/.weebot-remotion` (`:43, 108-110, 206-235`) | `ToolConfig` | automation, admin, webhook, coder, designer |
| `voice_input` | `VoiceInputTool` `weebot/tools/voice_input_tool.py:14` | `SpeechPort.transcribe` (`:60`) | `speech: SpeechPort` | admin, webhook |
| `voice_output` | `VoiceOutputTool` `weebot/tools/voice_output_tool.py:18` | `SpeechPort.synthesize` (`:81`) | `speech: SpeechPort` | admin, webhook |
| `youtube_download` | `YouTubeDownloadTool` `weebot/tools/youtube_download_tool.py:60` | `yt-dlp` subprocess, 10-minute YouTube cap, 300 s timeout (`:76-79, 322-401`) | none | none |

Roles: `weebot/tools/tool_registry.py:27-177`.

Path guards: `video_gen` checks `output_path` before any work (`video_gen_tool.py:388-391`); `youtube_download` resolves it against the cwd (`youtube_download_tool.py:199, 273-284`); `remotion_video` accepts only a `project` matching `^[a-z0-9][a-z0-9_-]{0,48}$` and a composition id, and builds every path itself under `Output/remotion` (`remotion_video.py:47-48, 104-105, 157-185`), passing the child only `_ENV_KEYS` (`:113-114`).

Consequences (read from source, not run):
- `image_gen` checks the workspace only in `_download_image` (`image_gen_tool.py:777-796, 813`). SVG kinds write `params.output_path` as given (`:926-956`), as do the SVG fallback (`:851-859`) and xAI base64 images (`:553-559`). An absolute path writes outside the workspace.
- `video_ingest` `export_jsonl` (`video_ingest_tool.py:326-359`) and `voice_output` (`voice_output_tool.py:77-82`) also write to an unchecked `output_path`.
- `youtube_download` is in no role, so no agent built from the role table can call it. Yet the built-in skills `youtube-download` (`weebot/skills/builtin/youtube-download/SKILL.md:9, 15-21`) and `remotion-video` tell the agent to use it. It also passes a model-chosen `js_runtime` executable path to yt-dlp (`youtube_download_tool.py:385-393`).
- `image_gen`'s raster branch opens an `aiohttp.ClientSession` it never uses (`image_gen_tool.py:937-944`).
- Paid calls (`image_gen` openrouter, `video_gen`) match no `WEEBOT_OUTBOUND_TOOL_PATTERNS` entry (`weebot/config/settings.py:394-404`), so they do not ask.
- `video_ingest` and `youtube_download` output is fenced as untrusted (`weebot/core/trust_boundary.py:65-67`).

## Connected to
- **Built by** `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`); collaborators from `Container.tool_wiring` (`application/di/_factories.py:430-469`).
- **Feeds** `KnowledgeTool` search (`video_ingest` stores chunks through the same `ToolRepositoryPort`, `video_ingest_tool.py:172-177`); the `reify_skill` and `remotion-video` built-in skills (card `tools/BuiltinSkills.md`).
- **Looks like but is not:** `apify_youtube_transcript` (card `tools/IntegrationTools.md`), a cloud actor.

## If you change this
**Hits:** `tests/unit/test_image_gen_safety.py`, `tests/unit/test_ideogram_cascade.py`, `tests/unit/test_verifier_readonly_tripwire.py`, `tests/unit/application/flows/test_quality_gates_are_loud.py`, `tests/integration/test_security_penetration.py`, `tests/unit/tools/test_remotion_video.py`, `tests/unit/tools/test_video_ingest_tool.py`, `tests/unit/fixes/test_w55_tool_wiring.py`, `tests/unit/test_di_registries_are_wired.py`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/test_trust_boundary.py`, `tests/unit/test_personality_manager.py`, `tests/unit/fixes/test_outbound_tools_ask.py`.
**Does not hit:** the guard chain (none is a shell tool); `KnowledgeTool` itself.

## Surfaces
Files under `Output/` (`image_gen_tool.py:929`, `youtube_download_tool.py:197`, `remotion_video.py:105`) and `WORKSPACE_ROOT` (`voice_output_tool.py:78`); the knowledge base.

## See
`weebot/tools/image_gen_tool.py`
