---
name: scientific-book
description: Author a scientific book in Greek (or another language) as a print-ready PDF via LaTeX — math equations, tables, figures, code listings, and bibliography. Compiles with XeLaTeX + polyglossia + a locked preamble, then self-heals compile errors until the PDF passes a print-readiness preflight. Triggered for any request to produce a book, textbook, monograph, or long structured scientific document as a PDF.
metadata:
  emoji: 📘
  trust: trusted
  provenance:
    origin: human
  requires_toolsets: []
  fallback_for_toolsets: []
---

# Scientific Book (LaTeX)

Produce a **print-ready PDF** of a scientific book. Default language is **Greek (el)**.
The strongest available model authors content (Opus 4.8 / `AUTHORING` profile); the
toolchain and self-heal loop guarantee it compiles.

## Golden rules

1. **Never edit the preamble.** Use the locked, tested preamble at
   `weebot/infrastructure/document/templates/greek_scientific_preamble.tex`. You author
   **body-only LaTeX** (content between `\begin{document}` and `\end{document}`), never
   package loads or fonts. The preamble's load order is fragile and hard-won — see its
   header comment.
2. **Engine is XeLaTeX or LuaLaTeX.** Build with `latexmk -xelatex -shell-escape main.tex`
   or `latexmk -lualatex -shell-escape main.tex`. Never pdfLaTeX (Unicode Greek needs
   `fontspec` + `polyglossia`). The same locked preamble compiles under both engines;
   `BookGenerationFlow` tries XeLaTeX first and automatically falls back to LuaLaTeX if a
   clean PDF isn't reached (engine strategy-switch). LuaLaTeX additionally needs the
   `texlive-luatex` runtime installed. `-shell-escape` is for `minted` and runs **only
   inside the sandbox**.
3. **Every element is labelled and cross-referenced** with `\cref{}` using the shared
   convention: `chap:`, `sec:`, `eq:`, `tab:`, `fig:`, `lst:`. The preamble already
   defines the Greek `\cref` names (κεφάλαιο, ενότητα, εξίσωση, πίνακας, σχήμα, κώδικας).
4. **A run is done only when** it compiles with 0 errors, all refs/cites resolve, there
   are **zero missing-glyph warnings**, and the print-readiness preflight passes
   (all fonts embedded). Otherwise, fix and recompile.

## Element idioms (Greek)

**Math** — standard amsmath; Greek prose inside math via `\text{...}` (main font covers Greek):
```latex
\begin{equation}
  e^{i\pi} + 1 = 0 . \label{eq:euler}
\end{equation}
Η \cref{eq:euler} ...  % → "Η εξίσωση (1) ..."
```

**Tables** — `booktabs`; use Greek decimal comma (`3{,}14159`):
```latex
\begin{table}[htbp]
  \centering \caption{...} \label{tab:constants}
  \begin{tabular}{@{}lcl@{}}\toprule ... \\ \midrule ... \\ \bottomrule \end{tabular}
\end{table}
```

**Figures** — prefer reproducible native `tikz`/`pgfplots` over external images:
```latex
\begin{figure}[htbp]\centering
  \begin{tikzpicture}\begin{axis}[xlabel={$p$},ylabel={$H(p)$}]
    \addplot {-x*log2(x)-(1-x)*log2(1-x)};
  \end{axis}\end{tikzpicture}
  \caption{...} \label{fig:entropy}
\end{figure}
```

**Code** — `minted` inside a `listing` float; Greek comments are fine:
```latex
\begin{listing}[htbp]
\begin{minted}{python}
def f(x):
    # Ελληνικό σχόλιο
    return x
\end{minted}
\caption{...} \label{lst:example}
\end{listing}
```

**Bibliography** — `biblatex`/`biber`: cite with `\autocite{key}`, entries go in `refs.bib`,
end matter has `\printbibliography`.

## Workflow

1. **Outline** the book (parts → chapters → sections) as structured data
   (`weebot/domain/models/book.py` :: `Book`).
2. **Assemble** `main.tex`: `\input` the locked preamble, `\frontmatter` (title, TOC),
   `\mainmatter` chapters, `\backmatter` `\printbibliography`.
3. **Compile & self-heal** with `LatexCompilerService`
   (`weebot/infrastructure/document/latex_compiler.py`). It parses the log into structured
   `CompileError`s. Route each up the escalation ladder (deterministic fix → content patch
   → strategy switch → asset regen → bisect). A repeated error signature must escalate,
   never retry the same fix.
4. **Preflight** with `preflight_pdf` (`weebot/infrastructure/document/preflight.py`).
   Any issue re-enters step 3.
5. **Deliver** the PDF + source tree to `Output/<book-slug>/`.

A minimal, verified end-to-end example lives in `examples/scientific_book_greek/`.
