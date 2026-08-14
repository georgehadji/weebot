# Complete E2E TeX Workflow — Manuscript → Print-Ready SWOP v2 CMYK PDF

> **Scope of this research.** What weebot still needs to take a book from the
> *initial manuscript* all the way to a **final, print-ready PDF in CMYK, U.S.
> Web Coated (SWOP) v2, PDF/X-conformant** — the file a US commercial
> (web-offset) print shop accepts without kickback. This complements
> `tasks/scientific-book-latex-plan.md` (which covers authoring→compile) and the
> now-merged XeLaTeX/LuaLaTeX pipeline.
>
> **TL;DR.** The compile half is done (XeLaTeX **and** LuaLaTeX both verified,
> fonts embedded, self-heal loop, font-embedding preflight). The **prepress
> half is the gap**: LaTeX emits an **RGB** PDF, and "SWOP v2" is fundamentally
> a **color-management + PDF/X** requirement that LaTeX does not do. The missing
> stages are (1) manuscript ingestion, (2) **ICC color conversion to SWOP v2
> CMYK**, (3) **PDF/X packaging** (output intent, boxes, bleed), and (4) a real
> **print preflight** (color, resolution, ink limit, boxes) with **veraPDF**
> validation. None of this is exotic — Ghostscript + lcms + veraPDF + poppler
> cover it — but it needs the right recipe, a couple of extra tools, and the
> **SWOP v2 ICC profile** in the sandbox image.

---

## 1. Terminology (so the target is unambiguous)

- **U.S. Web Coated (SWOP) v2** — an Adobe **ICC output profile** describing the
  CMYK behavior of US publication web-offset printing on coated stock (SWOP =
  Specifications for Web Offset Publications). "Make it SWOP v2" means: **all
  color is DeviceCMYK separated for this profile**, and the PDF carries it as
  its **OutputIntent**. Total Area Coverage (TAC) limit ≈ **300%**.
- **PDF/X** — the ISO 15930 family of print-exchange PDF subsets. Relevant here:
  - **PDF/X-1a:2001** — CMYK + spot **only**, **no** live transparency, **no**
    ICC-tagged RGB, all fonts embedded, OutputIntent required. The safest,
    most-universally-accepted deliverable for CMYK offset. *Recommended default.*
  - **PDF/X-4** — allows live transparency and ICC color; more modern, accepted
    by most shops, but riskier with older RIPs. Offer as an option.
- **OutputIntent** — the PDF object naming the target print condition (the SWOP
  v2 ICC profile). Required by every PDF/X.
- **TrimBox / BleedBox** — PDF page boxes defining the finished trim and the
  bleed margin. Print shops trim to TrimBox; art must extend to BleedBox.

---

## 2. Current state vs. target

| Stage | Now (merged) | Needed for SWOP v2 PDF/X |
|---|---|---|
| Manuscript → structured `Book` | ❌ starts from a `Book` spec already | ingestion (md/docx/txt → `Book`) |
| Author section bodies | ✅ LLM/stub `ContentProvider` | — |
| Assemble + compile | ✅ XeLaTeX **and** LuaLaTeX, self-heal loop | — |
| Color space | ❌ **DeviceRGB** output | **DeviceCMYK @ SWOP v2** + OutputIntent |
| PDF/X conformance | ❌ plain PDF 1.5 | **PDF/X-1a** (or X-4) |
| Bleed + page boxes | ❌ no bleed, no TrimBox/BleedBox | trim size + 3 mm bleed, boxes set |
| Preflight | ⚠️ **font embedding only** | color, ≥300 dpi images, ink limit, boxes, overprint, transparency |
| Validation | ❌ none | **veraPDF** PDF/X pass |

The compile half is solid; everything below Stage "Color space" is new work.

---

## 3. The end-to-end stage map

```
(0) INGEST      raw manuscript (md / docx / txt / outline + assets + refs.bib)
                    → normalize → Book(domain)                     [GAP]
(1) AUTHOR      fill section bodies (LLM / stub)                   [HAVE]
(2) ASSEMBLE    Book → main.tex + refs.bib + locked preamble       [HAVE]
(3) COMPILE     latexmk -xelatex|-lualatex → RGB PDF + self-heal   [HAVE]
(4) COLOR       RGB PDF → DeviceCMYK @ SWOP v2 (ICC)               [GAP]  ← core
(5) PACKAGE     PDF/X-1a: OutputIntent, TrimBox/BleedBox, bleed,
                transparency flatten, overprint, metadata          [GAP]
(6) PREFLIGHT   color / resolution / ink-limit / boxes / fonts     [PARTIAL]
(7) VALIDATE    veraPDF PDF/X-1a conformance (hard gate)           [GAP]
(8) DELIVER     final .pdf (+ preflight report)                    [GAP]
```

Stages 4–7 are the "prepress" phase. They run **after** a clean compile and are
**engine-independent** (they operate on the produced PDF), so they slot cleanly
behind the existing compile+font-preflight step.

---

## 4. Color management for SWOP v2 — the core gap (deep dive)

**Why LaTeX can't do it alone.** XeLaTeX/LuaLaTeX produce **DeviceRGB** (text
black is usually `0 0 0` RGB, colors via `xcolor` are RGB). There is no ICC
color management and no CMYK separation in the TeX engines. `xcolor`'s `[cmyk]`
model only *names* colors in CMYK; it does not ICC-convert RGB images or
guarantee a SWOP-correct separation, and it does not set an OutputIntent. So the
SWOP v2 requirement is met by a **post-compile ICC conversion + PDF/X packaging
step**, not in the `.tex`.

**Two things must be controlled:**

1. **Text/vector black must stay K-only.** Naive RGB→CMYK turns `0,0,0` into
   *rich black* `(c,m,y,k)` — small text then needs 4-plate registration and
   looks fuzzy. The conversion must map black text to **K-only (0,0,0,1)** with
   **overprint on**. Ghostscript's `-dBlackText`/black-preservation and
   `-dOverrideICC` + a proper black-point strategy handle this; simplest robust
   route is `-dBlackText=true -dBlackVector=true` (GS ≥ 9.55) so black text/line
   art is preserved to K.
2. **Everything else separates through the SWOP v2 ICC profile**, and the
   profile is embedded as the **OutputIntent**.

### 4.1 The Ghostscript recipe (grounded — gs 10.02.1 is present)

A **PDF/X-1a** build needs a small `PDFX_def.ps` that declares the OutputIntent
plus the gs conversion flags. Sketch:

```postscript
% PDFX_def.ps — names the SWOP v2 output intent
/ICCProfile (USWebCoatedSWOP.icc) def       % the SWOP v2 profile file
[ /Title (Book) /DOCINFO pdfmark
[ {Catalog} << /Version /1.4 >> /PUT pdfmark
[ /_objdef {icc_PDFX} /type /stream /OBJ pdfmark
[ {icc_PDFX} << /N 4 >> /PUT pdfmark            % N=4 → CMYK
[ {icc_PDFX} ICCProfile (r) file /PUT pdfmark
[ /_objdef {OutputIntent} /type /dict /OBJ pdfmark
[ {OutputIntent} <<
    /Type /OutputIntent /S /GTS_PDFX
    /OutputConditionIdentifier (CGATS TR 001 SWOP)
    /Info (U.S. Web Coated (SWOP) v2)
    /DestOutputProfile {icc_PDFX}
  >> /PUT pdfmark
[ {Catalog} << /OutputIntents [ {OutputIntent} ] >> /PUT pdfmark
```

```bash
gs -dPDFX -dBATCH -dNOPAUSE -dNOOUTERSAVE \
   -sDEVICE=pdfwrite -dCompatibilityLevel=1.3 \
   -sColorConversionStrategy=CMYK -dProcessColorModel=/DeviceCMYK \
   -dBlackText=true -dBlackVector=true \
   -sOutputICCProfile=USWebCoatedSWOP.icc \
   -dRenderIntent=1 \
   -o final_x1a.pdf PDFX_def.ps rgb_book.pdf
```

**Verified here:** a bare `-sColorConversionStrategy=CMYK` gs run on a compiled
Greek PDF **removed all `/DeviceRGB` and produced `/DeviceCMYK`** — the core
conversion works with the installed gs. **Not yet stamped** in that quick run:
the `OutputIntent` and `GTS_PDFXVersion` markers (0 found), which is exactly why
the **`PDFX_def.ps` + ICC profile** are mandatory — color conversion ≠ PDF/X.
That is the precise piece to implement.

### 4.2 PDF/X-1a vs PDF/X-4

Default to **PDF/X-1a** (must **flatten transparency** first — see §6; TikZ/
pgfplots opacity, some `minted` backgrounds, and PNG alpha are transparency
sources). Offer **PDF/X-4** as a flag for shops that accept it (keeps live
transparency + ICC, no flatten). Both carry the same SWOP v2 OutputIntent.

### 4.3 Ink limit (TAC)

SWOP v2 caps **Total Area Coverage at ~300%**. After conversion, measure
per-page ink coverage (`gs -sDEVICE=inkcov`) and, for images, verify no pixel
exceeds the limit (lcms/`tifficc` with the SWOP profile enforces this on
conversion). Rich photographic images may need **ink-limiting** during the ICC
transform (perceptual intent + the profile's TAC).

---

## 5. Manuscript ingestion (front of the pipeline)

"Initial manuscript" implies raw author input, not a ready `Book`. Needed:

- **Format adapters** → normalized `Book`: Markdown, `.docx`, plain text, or an
  outline. **Pandoc** is the natural converter (docx/md → structured AST →
  `Book` chapters/sections); an LLM structurer handles messy prose/outlines.
- **Asset ingestion**: collect figures/photos, record native resolution and
  color space, flag anything that will be < 300 dpi at placed size or is RGB
  (must convert in §6).
- **Bibliography ingestion**: `.bib` (have) or CSL-JSON/Zotero → `.bib`.
- **Math/table normalization**: author math as LaTeX or MathML→LaTeX (pandoc).

This is a new **application-layer** ingestion service producing the `Book`
domain object the existing flow already consumes.

---

## 6. Assets, geometry, and the other prepress gates

- **Image resolution**: contone images **≥ 300 dpi** at placed size, line-art /
  bitmap **≥ 600–1200 dpi**. Measure with `pdfimages -list` (x/y-ppi columns).
- **Image color**: RGB images ICC-converted to SWOP v2 CMYK (lcms/`tifficc` or
  during the gs pass); no ICC-tagged RGB survives in PDF/X-1a.
- **Bleed**: for any content touching the page edge, add **3 mm (0.125")**
  bleed. In LaTeX, drive page size = trim + bleed via `geometry`/`crop` or the
  document class; set the finished **TrimBox** and the **BleedBox** in the PDF.
- **Page boxes**: PDF/X requires a **TrimBox** (or ArtBox). Set TrimBox =
  finished size and BleedBox = trim + bleed. Tools: `gs` pdfmarks, or
  `qpdf`/`mutool` (both **missing** — add one).
- **Printer marks**: crop/registration/color-bar marks are usually added by the
  shop from the TrimBox; weebot's job is correct boxes, not marks (offer marks
  as an optional extra via `pdfpages`/`crop`).
- **Overprint**: black text overprints (set during §4 conversion).
- **Transparency**: for PDF/X-1a, **flatten** (gs `-dCompatibilityLevel=1.3`
  flattens on write) before/at conversion.
- **Fonts**: fully embedded + subset (**already enforced** by `preflight.py`).

---

## 7. Expanded preflight + validation

Extend the existing `preflight.py` (today: font embedding only) into a
**print-readiness gate** with deterministic checks, then a conformance pass:

| Check | Tool (installed?) |
|---|---|
| All fonts embedded + subset | `pdffonts` ✅ (have) |
| No DeviceRGB / no ICC-RGB (X-1a) | `gs` ✅ / `pdfimages -list` ✅ |
| OutputIntent = SWOP v2 present | parse PDF / `gs` ✅ |
| Image resolution ≥ 300/600 dpi | `pdfimages -list` ✅ |
| Ink limit (TAC) ≤ 300% | `gs -sDEVICE=inkcov` ✅ |
| TrimBox/BleedBox + bleed present | `pdfinfo -box` ✅ / `qpdf` ❌ |
| **PDF/X-1a conformance** | **veraPDF** ❌ (add) |

**veraPDF** is the authoritative open-source PDF/X validator and should be the
**hard gate** before delivery (pass/fail + machine-readable report). It is
**not installed** — add it (Java-based) to the sandbox image.

---

## 8. Tooling & sandbox-image additions (verified on this box)

| Tool | Purpose | Present? |
|---|---|---|
| Ghostscript (`gs` 10.02.1) | RGB→CMYK, PDF/X, OutputIntent, inkcov, flatten | ✅ |
| poppler (`pdffonts`/`pdfimages`/`pdfinfo`) | preflight introspection | ✅ |
| `texlive-luatex` | **LuaLaTeX runtime** (luatexbase, luaotfload) | ✅ (added this session) |
| **SWOP v2 ICC profile** (`USWebCoatedSWOP.icc`) | the target print condition | ❌ **must add** |
| **veraPDF** | PDF/X-1a/X-4 conformance gate | ❌ add |
| **qpdf** *or* **mutool** (mupdf) | set TrimBox/BleedBox, linearize | ❌ add |
| **lcms2** (`tifficc`) / ImageMagick+lcms | image ICC transforms, ink-limiting | ❌ add |
| **Pandoc** | manuscript (md/docx) → structured | ❌ add (ingestion) |

> **Licensing note on SWOP v2.** Only **FOGRA39** (European coated) and generic
> GS CMYK profiles ship on this box — **not** US SWOP v2. Adobe's
> "U.S. Web Coated (SWOP) v2" profile is freely redistributable under Adobe's
> ICC-profile license (bundled with Acrobat/Creative Suite) and is what US shops
> expect. Ship it in the TeX-Live/prepress Docker image. If Adobe redistribution
> is undesirable, the closest open equivalent is **GRACoL/CGATS21** (or keep
> FOGRA39 for European coated jobs) — but "SWOP v2" specifically means the Adobe
> profile, so make the **profile a configurable `PrintProfile` input**, defaulting
> to SWOP v2, so European/US/GRACoL targets are all reachable.

---

## 9. Where it lives in weebot (Clean Architecture)

Dependencies point inward; the prepress step is deterministic infrastructure
behind an application port, mirroring the existing `CompilerPort`/`PreflightPort`.

- **Domain (`weebot/domain/models/`)**
  - `PrintProfile` — target: `icc_profile` (default SWOP v2), `pdfx_standard`
    (X-1a/X-4), `trim_size`, `bleed_mm`, `tac_limit`, `min_image_dpi`.
  - Extend `PreflightReport` with typed findings: `color_space`, `resolution`,
    `ink_limit`, `boxes`, `pdfx_conformance` (not just font embedding).
- **Application (`weebot/application/document/`)**
  - Ports: `ColorConverterPort` (RGB PDF + `PrintProfile` → CMYK PDF/X),
    `PdfxValidatorPort` (PDF → conformance report), `ManuscriptIngestPort`
    (raw source → `Book`).
  - `BookGenerationFlow` gains a **prepress phase** after the compile/font gate:
    `compile → convert(SWOP v2) → set boxes/bleed → preflight → veraPDF`, with
    escalation (e.g., TAC over limit → re-run ICC with ink-limiting; RGB leftover
    → re-flatten; low-dpi image → surface to author).
- **Infrastructure (`weebot/infrastructure/document/`)**
  - `GhostscriptColorConverter` (implements `ColorConverterPort`; builds the
    `PDFX_def.ps`, runs the gs recipe from §4, routed through `BashGuard`).
  - `VeraPdfValidator` (implements `PdfxValidatorPort`).
  - `PandocManuscriptIngestor` (implements `ManuscriptIngestPort`).
  - Extend `preflight.py` with the color/resolution/ink/box checks (§7).

All external commands go through `BashGuard`, same as `LatexCompilerService`.

---

## 10. Phased implementation plan

1. **Prepress image** — Docker layer: gs (have), **SWOP v2 ICC**, **veraPDF**,
   **qpdf/mutool**, **lcms2/ImageMagick**, **pandoc**; plus `texlive-luatex`
   (done) and the existing XeLaTeX stack.
2. **Color+PDF/X core** — `GhostscriptColorConverter` + `PrintProfile`; RGB→
   SWOP v2 CMYK PDF/X-1a with OutputIntent and K-only black; unit-test on the
   Greek example (assert 0 DeviceRGB, OutputIntent present, fonts embedded).
3. **Geometry** — trim size + 3 mm bleed at the LaTeX layer; set TrimBox/BleedBox
   (qpdf/mutool or gs pdfmarks).
4. **Preflight++** — color/resolution/ink-limit/box gates in `preflight.py`.
5. **veraPDF gate** — `VeraPdfValidator` as the hard pass/fail before delivery.
6. **Ingestion** — `PandocManuscriptIngestor` (md/docx/txt → `Book`) + asset
   resolution/color intake.
7. **Flow wiring + escalation** — prepress phase in `BookGenerationFlow` with
   the fix ladder; `GenerationResult` reports `pdfx_ok`, `color_space`,
   `ink_ok`, `veraPDF` summary.

---

## 11. Open decisions / risks

- **SWOP v2 profile distribution** — ship Adobe's profile (license OK) vs. make
  the profile a required build input. *Recommend: bundle SWOP v2, keep it a
  configurable `PrintProfile` so GRACoL/FOGRA are one flag away.*
- **X-1a vs X-4 default** — X-1a is safest (needs transparency flatten, which can
  rasterize complex TikZ). *Recommend X-1a default, X-4 opt-in.*
- **Rich black vs K-only** — enforce K-only for text/thin rules; allow controlled
  rich black only for large solids. Gs black-preservation flags cover this.
- **Image pipeline** — vector-heavy scientific books convert cleanly; photo-heavy
  books need per-image ICC + ink-limiting (lcms) before/at the gs pass.
- **veraPDF in CI** — Java dependency; gate the real prepress tests on tool
  presence (same `skipif` pattern the LaTeX tests already use).
