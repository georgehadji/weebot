---
name: remotion-video
description: Make videos from code with Remotion through the remotion_video tool — motion graphics, explainer and promo videos, title cards, lower thirds, animated charts and data stories, captions/subtitles over footage, slideshows from images, social clips with text animation. Use when the video is made of text, shapes, data, images or supplied clips and must be exact and editable. For realistic generated footage (people, scenes, camera moves) use video_gen instead.
metadata:
  emoji: 🎬
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: ["remotion_video"]
  fallback_for_toolsets: []
  homepage: https://www.remotion.dev
---

# Remotion videos (React code to MP4)

Remotion renders a React component once per frame in headless Chrome, then encodes the frames. Every frame is a pure function of the frame number, so the video is exact, repeatable and easy to change.

## Pick the right tool

| The video needs | Use |
|---|---|
| Text, logos, shapes, charts, data, captions, image slideshows, UI mockups | `remotion_video` |
| Realistic generated footage: people, places, camera moves, "cinematic" | `video_gen` |
| A downloaded clip | `youtube_download`, then `remotion_video` to add titles or captions |

You can combine them: generate a clip with `video_gen`, put it in `public/`, and use `remotion_video` to add titles, captions and an outro.

## Workflow

1. `remotion_video(action="scaffold", project="launch-promo")` writes `Output/remotion/launch-promo/src/` (`index.ts`, `Root.tsx`, `Main.tsx`) and `public/`.
2. Edit `src/Main.tsx` and `src/Root.tsx` with `file_editor`. Add one `<Composition>` per video in `Root.tsx`, with its `id`, `fps`, `durationInFrames`, `width` and `height`.
3. `remotion_video(action="compositions", project=…)` checks that the project bundles and lists the composition ids.
4. `remotion_video(action="still", project=…, composition="Main", frame=45)` renders one PNG. Look at it before a full render, and check a few key frames.
5. `remotion_video(action="render", project=…, composition="Main", props={…})` writes `out/Main.mp4`. Use `codec="vp9"` for webm, `"gif"` for a GIF, `"prores"` for editing software.

Formats: 1920×1080 for landscape, 1080×1920 for Reels/Shorts/TikTok, 1080×1080 for square. Use 30 fps unless asked otherwise.

## Rules for Remotion code

- **Animate from the frame only.** Use `useCurrentFrame()` and `useVideoConfig()`, and derive every value from them with `interpolate(frame, [start, end], [from, to], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})` or `spring({frame, fps})`.
- **No CSS animations, transitions, `setTimeout`, `setInterval` or `Date.now()`.** They do not follow the frame and they flicker or freeze in the render.
- **No `Math.random()`.** Use `random('seed')` from `remotion`, so every render matches.
- **Timing:** `<Sequence from={30} durationInFrames={60}>` places a part in time. `<Series>` plays parts one after another. Seconds × fps = frames.
- **Layout:** `<AbsoluteFill>` for full-frame layers. Plain inline styles or CSS work.
- **Media:** put files in `public/` and load them with `staticFile('logo.png')`. Use `<Img>`, `<OffthreadVideo>` and `<Audio>` from `remotion`, not plain `<img>`/`<video>`, so frames wait for them to load.
- **Data:** pass changing content (titles, numbers, captions) as `props` on render, and give them `defaultProps` in `Root.tsx`.
- **Packages:** only `remotion`, `react` and `react-dom` are installed. Use system fonts or font files in `public/` (load them with `@font-face` in a `<style>` tag). Do not import other npm packages.
- Apply the user's brand: colors, fonts, logo. Keep text on screen long enough to read (about 3 frames per character, 2 s minimum).

## Checks before you hand it over

- Render at least one still and look at it for clipped text, contrast and safe margins (keep text 5% inside the edges).
- After `render`, give the user the path to the output file, its length and its size.

## License

Remotion is not MIT. Its license is free for individuals, non-profits and for-profit companies of up to 3 people. Larger companies need a company license from remotion.pro. If the user's work is for such a company, tell them once.
