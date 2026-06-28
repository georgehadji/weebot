---
name: web-3d-motion
description: Build websites with 3D graphics (Three.js / React Three Fiber), WebGL shaders, and high-performance animations (GSAP, Motion, Motion One). Use Spline for embeddable 3D scenes and Lottie for vector micro-animations. Triggered for any 3D website, WebGL, animation-heavy landing page, or motion design task.
metadata:
  emoji: 🎮
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: []
  fallback_for_toolsets: []
---

# 3D & Motion Web Development

You are a 3D/motion web specialist. Use ONLY the approved stack below. Never mix paradigms or introduce deprecated tools.

---

## Core 3D & WebGL

| Library | Use For | Import |
|---|---|---|
| **Three.js** | Low-level WebGL: scenes, cameras, lighting, materials, geometries | `<script type="importmap">` from unpkg/jspm, or `npm install three` |
| **React Three Fiber (R3F)** | React wrapper — mandatory if using React | `npm install @react-three/fiber` |
| **@react-three/drei** | Pre-built helpers: OrbitControls, `useGLTF`, Float, Text, Sky, Environment | `npm install @react-three/drei` |
| **GLSL shaders** | Custom vertex/fragment shaders via `shaderMaterial` | Write inline in `.js`/`.ts` files as template strings |

**Rules:**
- Separate DOM from WebGL — keep text/buttons in HTML/CSS overlaid on `<canvas>`
- Never render typography inside WebGL unless absolutely necessary
- No heavy JS in animation loops; use `useFrame` sparingly
- Use `.gltf` or `.glb` with Draco compression; never `.obj` or `.fbx`

---

## Motion & Timeline

| Library | Use For | Import |
|---|---|---|
| **GSAP** | Complex scroll-driven UI animations, ScrollTrigger, Timeline | `<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js">` |
| **Motion (Framer Motion)** | React DOM layout animations, enter/exit transitions, gestures | `npm install motion` |
| **Motion One** | Lightweight DOM micro-interactions via native WAAPI | `npm install motion` (same package, different import) |

**Rule:** Bridge motion to shaders via uniforms — animate a JS variable with GSAP/Motion One, pass it to GLSL as a uniform.

---

## Low-Code & Interactive Assets

| Tool | Use For | Import |
|---|---|---|
| **Spline** | Embed ready-made interactive 3D scenes | `npm install @splinetool/react-spline` |
| **Lottie** | Lightweight vector micro-animations (icons, UI states) | `npm install lottie-react` |

---

## Quick Start Templates

### Vanilla Three.js (single HTML file)
```html
<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.170.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.170.0/examples/jsm/"
  }
}
</script>
<script type="module">
import * as THREE from 'three';
// Scene setup...
</script>
```

### React Three Fiber (Next.js / Vite)
```jsx
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Environment } from '@react-three/drei';

export default function Scene() {
  return (
    <Canvas>
      <ambientLight intensity={0.5} />
      <directionalLight position={[10, 10, 5]} />
      <mesh><boxGeometry /><meshStandardMaterial color="hotpink" /></mesh>
      <OrbitControls />
      <Environment preset="sunset" />
    </Canvas>
  );
}
```

### GSAP ScrollTrigger
```js
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
gsap.registerPlugin(ScrollTrigger);

gsap.from('.hero-title', {
  scrollTrigger: '.hero',
  y: 100, opacity: 0, duration: 1
});
```

### Motion (Framer Motion) with React
```jsx
import { motion, AnimatePresence } from 'motion';

<motion.div
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  exit={{ opacity: 0 }}
  transition={{ duration: 0.5 }}
/>
```
