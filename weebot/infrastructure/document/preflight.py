"""Print-Readiness Preflight — hard gate before a PDF is shipped for printing.

"Compiles cleanly" is not the same as "print-ready". A professional print shop
requires, at minimum, that every font is embedded. This validator inspects the
produced PDF and reports issues that must re-enter the self-heal loop rather than
ship. It is deliberately deterministic (uses ``pdffonts`` from poppler-utils).

Further gates (color model / ≥300 DPI images / PDF/X-4 / geometry) are described
in tasks/scientific-book-latex-plan.md §6.5 and slot in here as they land.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class PreflightIssue(BaseModel):
    check: str
    message: str


class PreflightReport(BaseModel):
    ok: bool = Field(default=False)
    issues: list[PreflightIssue] = Field(default_factory=list)
    fonts_total: int = Field(default=0)
    fonts_not_embedded: int = Field(default=0)


def _parse_pdffonts(output: str) -> tuple[int, int]:
    """Return (total_fonts, not_embedded_count) from ``pdffonts`` output."""
    lines = output.splitlines()
    if len(lines) < 3:
        return 0, 0
    rows = lines[2:]  # skip header + separator
    total = 0
    not_embedded = 0
    for row in rows:
        if not row.strip():
            continue
        cols = row.split()
        if len(cols) < 5:
            continue
        total += 1
        # pdffonts columns: name type encoding emb sub uni object-id
        # 'emb' is the 4th-from-relevant field; locate the yes/no triple.
        emb = cols[-4]
        if emb == "no":
            not_embedded += 1
    return total, not_embedded


def preflight_pdf(pdf_path: str | Path) -> PreflightReport:
    """Run the print-readiness checks on ``pdf_path``."""
    pdf = Path(pdf_path)
    issues: list[PreflightIssue] = []

    if not pdf.exists():
        return PreflightReport(
            ok=False,
            issues=[PreflightIssue(check="exists", message="PDF not found")],
        )

    total = not_embedded = 0
    if shutil.which("pdffonts"):
        try:
            out = subprocess.run(
                ["pdffonts", str(pdf)], capture_output=True, text=True, timeout=60
            ).stdout
            total, not_embedded = _parse_pdffonts(out)
            if not_embedded > 0:
                issues.append(
                    PreflightIssue(
                        check="font_embedding",
                        message=f"{not_embedded} font(s) not embedded (must be 0 for print)",
                    )
                )
        except (subprocess.SubprocessError, OSError) as exc:
            issues.append(
                PreflightIssue(check="font_embedding", message=f"pdffonts failed: {exc}")
            )
    else:
        issues.append(
            PreflightIssue(
                check="font_embedding",
                message="pdffonts unavailable — cannot verify embedding",
            )
        )

    return PreflightReport(
        ok=not issues,
        issues=issues,
        fonts_total=total,
        fonts_not_embedded=not_embedded,
    )
