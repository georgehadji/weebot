"""LatexCompilerService — compile a LaTeX project to PDF and report structured results.

Runs ``latexmk -xelatex`` (Greek needs XeLaTeX + fontspec + polyglossia) in a
working directory, routes the command through :class:`BashGuard`, and parses the
resulting ``.log`` into a :class:`CompileResult` for the self-heal loop.

SECURITY: ``minted`` requires ``-shell-escape``, which is dangerous on an
untrusted host. This service is intended to run **inside the sandbox**
(``weebot/infrastructure/sandbox/``). ``shell_escape`` defaults to ``False``;
callers on the sandbox path opt in explicitly. The command is still evaluated by
``BashGuard`` and refused if BLOCKED.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from weebot.core.bash_guard import BashGuard, RiskLevel
from weebot.domain.models.book import CompileError, CompileErrorCategory, CompileResult
from weebot.infrastructure.document.log_parser import parse_log

# Engines that produce Unicode-Greek output via fontspec + polyglossia. Both use
# the same locked preamble; pdfLaTeX is intentionally unsupported (no fontspec).
SUPPORTED_ENGINES: tuple[str, ...] = ("xelatex", "lualatex")


class LatexCompilerService:
    """Compile a ``.tex`` entry point to PDF, returning structured results."""

    def __init__(
        self,
        engine: str = "xelatex",
        *,
        guard: BashGuard | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        if engine not in SUPPORTED_ENGINES:
            raise ValueError(
                f"Unsupported engine {engine!r}; expected one of {SUPPORTED_ENGINES} "
                "(pdfLaTeX cannot render Unicode Greek via fontspec)."
            )
        self._engine = engine
        self._guard = guard or BashGuard()
        self._timeout = timeout_seconds

    @property
    def engine(self) -> str:
        """The TeX engine this service compiles with (xelatex/lualatex)."""
        return self._engine

    def with_engine(self, engine: str) -> "LatexCompilerService":
        """Return a sibling service that compiles with a different engine.

        Preserves the guard and timeout, so the escalation ladder's engine
        strategy-switch (XeLaTeX ↔ LuaLaTeX) reuses the same safety config.
        """
        return LatexCompilerService(
            engine, guard=self._guard, timeout_seconds=self._timeout
        )

    @staticmethod
    def toolchain_available(engine: str = "xelatex") -> bool:
        """True if latexmk and the requested engine are on PATH."""
        return bool(shutil.which("latexmk")) and bool(shutil.which(engine))

    @staticmethod
    def available_engines() -> list[str]:
        """Supported engines actually present on PATH (with latexmk), in order."""
        if not shutil.which("latexmk"):
            return []
        return [e for e in SUPPORTED_ENGINES if shutil.which(e)]

    @staticmethod
    def locked_preamble_path() -> Path:
        """Absolute path to the tested, locked Greek preamble template."""
        return (
            Path(__file__).resolve().parent
            / "templates"
            / "greek_scientific_preamble.tex"
        )

    @classmethod
    def prepare_project(cls, project_dir: str | Path) -> Path:
        """Materialize the locked preamble into ``project_dir`` as ``preamble.tex``.

        The assembled ``main.tex`` should ``\\input{preamble.tex}`` so the project
        is self-contained and location-independent (safe to copy into a sandbox).
        """
        project = Path(project_dir)
        project.mkdir(parents=True, exist_ok=True)
        dest = project / "preamble.tex"
        shutil.copyfile(cls.locked_preamble_path(), dest)
        return dest

    def _build_command(self, main_tex: str, shell_escape: bool) -> list[str]:
        cmd = ["latexmk", f"-{self._engine}", "-interaction=nonstopmode"]
        if shell_escape:
            cmd.append("-shell-escape")
        cmd.append(main_tex)
        return cmd

    def compile(
        self,
        project_dir: str | Path,
        main_tex: str = "main.tex",
        *,
        shell_escape: bool = False,
    ) -> CompileResult:
        """Compile ``main_tex`` inside ``project_dir`` and return a CompileResult."""
        project = Path(project_dir)
        cmd = self._build_command(main_tex, shell_escape)

        # Route through the safety guard before executing.
        risk, _ = self._guard.evaluate(" ".join(cmd))
        if risk == RiskLevel.BLOCKED:
            return CompileResult(
                ok=False,
                engine=self._engine,
                errors=[
                    CompileError(
                        category=CompileErrorCategory.UNKNOWN,
                        message="Compile command blocked by BashGuard",
                        fatal=True,
                    )
                ],
            )

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(project),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            proc = None
            timed_out = True
            stdout = exc.stdout or ""
        else:
            stdout = proc.stdout or ""

        log_path = project / (Path(main_tex).stem + ".log")
        log_text = log_path.read_text(errors="replace") if log_path.exists() else stdout

        errors = parse_log(log_text)
        if timed_out:
            errors.append(
                CompileError(
                    category=CompileErrorCategory.TIMEOUT,
                    message=f"latexmk exceeded {self._timeout}s",
                    fatal=True,
                )
            )

        pdf_path = project / (Path(main_tex).stem + ".pdf")
        pdf_exists = pdf_path.exists()
        page_count = _pdf_page_count(pdf_path) if pdf_exists else None

        blocking = any(e.fatal for e in errors) or any(
            e.category
            in {
                CompileErrorCategory.UNDEFINED_REFERENCE,
                CompileErrorCategory.UNDEFINED_CITATION,
                CompileErrorCategory.MISSING_GLYPH,
            }
            for e in errors
        )
        ok = pdf_exists and not blocking and not timed_out

        return CompileResult(
            ok=ok,
            pdf_path=str(pdf_path) if pdf_exists else None,
            page_count=page_count,
            errors=errors,
            log_tail="\n".join(log_text.splitlines()[-25:]),
            engine=self._engine,
        )


def _pdf_page_count(pdf_path: Path) -> int | None:
    """Best-effort page count via pdfinfo (poppler-utils), else None."""
    if not shutil.which("pdfinfo"):
        return None
    try:
        out = subprocess.run(
            ["pdfinfo", str(pdf_path)], capture_output=True, text=True, timeout=30
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    for line in out.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None
