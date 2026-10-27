---
type: object
name: Media tools
code: ImageGenTool, VideoGenTool, VideoIngestTool, RemotionVideoTool, VoiceInputTool, VoiceOutputTool, YouTubeDownloadTool
cluster: tools
universe: live
status: verified
verified: 2026-10-27
commit: f36ab8e5
---

# Media tools

Tools that make or ingest images, video and audio: `image_gen`, `video_gen`, `video_ingest`, `remotion_video`, `voice_input`, `voice_output`, and `youtube_download`.

## Why this shape
Each tool owns its backend and writes files under the workspace. Paid generation reads provider keys straight from the environment and falls back to a free path (SVG templates for images, `weebot/tools/image_gen_tool.py:596-629`). Tools whose backend is a port (`ToolRepositoryPort`, `SpeechPort`) refuse to construct without it (`weebot/tools/video_ingest_tool.py:229-236`, `weebot/tools/voice_input_tool.py:42-49`, `weebot/tools/voice_output_tool.py:50-57`), and the registry supplies it from `wiring()["collaborators"]` (`weebot/application/di/_factories.py:504-506`).

## Shape

| Tool name | Class, file:line | Backend | Collaborator | Roles |
|---|---|---|---|---|
| `image_gen` | `ImageGenTool` `weebot/tools/image_gen_tool.py:257` | kinds `hero/card/icon/logo/testimonial` (SVG), `svg/ai` (Replicate if `REPLICATE_API_TOKEN`, else themed SVG), `openrouter` (OpenRouter, xAI or Ideogram direct, `IMAGE_CASCADE`) (`weebot/tools/image_gen_tool.py:896-948, 589-622`) | none | admin, webhook, coder, designer |
| `video_gen` | `VideoGenTool` `weebot/tools/video_gen_tool.py:53` | OpenRouter video models or xAI direct (`weebot/tools/video_gen_tool.py:108-162, 284-292`) | none | automation, admin, webhook, coder, designer |
| `video_ingest` | `VideoIngestTool` `weebot/tools/video_ingest_tool.py:172` | `youtube_transcript_api` + oEmbed; actions `ingest_youtube`, `list_sources`, `export_jsonl` (`weebot/tools/video_ingest_tool.py:180-184`) | `repo: ToolRepositoryPort` | researcher, admin, webhook |
| `remotion_video` | `RemotionVideoTool` `weebot/tools/remotion_video.py:118` | `node remotion_render.cjs` in `REMOTION_HOST` or `~/.weebot-remotion` (`weebot/tools/remotion_video.py:44, 109-111, 209-238`) | `ToolConfig` | automation, admin, webhook, coder, designer |
| `voice_input` | `VoiceInputTool` `weebot/tools/voice_input_tool.py:15` | `SpeechPort.transcribe` (`weebot/tools/voice_input_tool.py:63`) | `speech: SpeechPort` | admin, webhook |
| `voice_output` | `VoiceOutputTool` `weebot/tools/voice_output_tool.py:19` | `SpeechPort.synthesize` (`weebot/tools/voice_output_tool.py:90`) | `speech: SpeechPort` | admin, webhook |
| `youtube_download` | `YouTubeDownloadTool` `weebot/tools/youtube_download_tool.py:61` | `yt-dlp` subprocess, 10-minute YouTube cap, 300 s timeout (`weebot/tools/youtube_download_tool.py:37-39, 402-408`) | none | researcher, admin |

Roles: `weebot/application/services/tool_registry.py:27-185`.

Path guards: `image_gen` checks `output_path` before any branch runs (`weebot/tools/image_gen_tool.py:922-927`, `_sanitize_output_path` `:780-799`); `video_gen` checks `output_path` before any work (`weebot/tools/video_gen_tool.py:405-408`); `video_ingest` `export_jsonl` and `voice_output` resolve it with `core.output_path`, which refuses `..` and absolute paths outside the project (`weebot/tools/video_ingest_tool.py:335-340`, `weebot/tools/voice_output_tool.py:82-87`, `weebot/core/output_path.py:18-33`); `youtube_download` resolves it against the cwd (`weebot/tools/youtube_download_tool.py:202, 276-284`); `remotion_video` accepts only a `project` matching `^[a-z0-9][a-z0-9_-]{0,48}$` and a composition id, and builds every path itself under `Output/remotion` (`weebot/tools/remotion_video.py:48-49, 105-106, 160-189`), passing the child only `_ENV_KEYS` (`weebot/tools/remotion_video.py:114-115`).

Consequences (read from source, not run):
- `image_gen`, `video_gen` are paid per call and match `WEEBOT_OUTBOUND_TOOL_PATTERNS` (`weebot/config/settings.py:445-458`), so the guard chain wraps them and they always ask (see the BaseTool card). `remotion_video`, `video_ingest` and the voice tools match no pattern.
- `youtube_download` passes a model-chosen `js_runtime` executable path to yt-dlp (`weebot/tools/youtube_download_tool.py:388-396`). The built-in skill `youtube-download` names it (`weebot/skills/builtin/youtube-download/SKILL.md:9, 15-21`), but only `researcher` and `admin` have it.
- `image_gen`'s raster branch opens an `aiohttp.ClientSession` it never uses (`weebot/tools/image_gen_tool.py:964-967`).
- `video_ingest` and `youtube_download` declare `OutputTrust.EXTERNAL`, so their output is fenced and taints the session (`weebot/tools/video_ingest_tool.py:187`, `weebot/tools/youtube_download_tool.py:89`); the other five tools are `LOCAL`. The rules are in `weebot/core/trust_boundary.py:58-90`.

Spend: every paid 200 from the image and video generators, OpenRouter or direct, is reported to the session cost meter through `weebot/core/media_spend.py` as an estimate (`MEDIA_CALL_USD` in `weebot/config/model_refs.py`). A paid answer with nothing usable stops the model cascade, so the image or clip is never bought twice.

## Connected to
- **Built by** `RoleBasedToolRegistry` (card `tools/RoleBasedToolRegistry.md`); collaborators from `Container.tool_wiring` (`weebot/application/di/_factories.py:480-522`).
- **Feeds** `KnowledgeTool` search (`video_ingest` stores chunks through the same `ToolRepositoryPort`, `weebot/tools/video_ingest_tool.py:173-178`); the `reify_skill` and `remotion-video` built-in skills (card `tools/BuiltinSkills.md`).
- **Looks like but is not:** `apify_youtube_transcript` (card `tools/IntegrationTools.md`), a cloud actor.

## If you change this
**Hits:** `tests/unit/test_image_gen_safety.py`, `tests/unit/test_ideogram_cascade.py`, `tests/unit/test_verifier_readonly_tripwire.py`, `tests/unit/application/flows/test_quality_gates_are_loud.py`, `tests/integration/test_security_penetration.py`, `tests/unit/tools/test_remotion_video.py`, `tests/unit/tools/test_video_ingest_tool.py`, `tests/unit/fixes/test_w55_tool_wiring.py`, `tests/unit/test_di_registries_are_wired.py`, `tests/unit/core/test_trust_boundary_registry.py`, `tests/unit/test_trust_boundary.py`, `tests/unit/test_personality_manager.py`, `tests/unit/fixes/test_outbound_tools_ask.py`, `tests/unit/fixes/test_a26_followups.py`.
**Does not hit:** the shell guards (BashGuard, ExecApprovalPolicy); `KnowledgeTool` itself.

## Surfaces
Files under `Output/` (`image_gen_tool.py:954`, `youtube_download_tool.py:200`, `remotion_video.py:106`) and `WORKSPACE_ROOT` (`voice_output_tool.py:81`); the knowledge base.

## See
`weebot/tools/image_gen_tool.py`
