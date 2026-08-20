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

import os
import shutil
import subprocess
from pathlib import Path

from weebot.core.bash_guard import BashGuard, RiskLevel
from weebot.domain.models.book import CompileError, CompileErrorCategory, CompileResult
from weebot.infrastructure.document.log_parser import parse_log

_DRAIN_TIMEOUT_SECONDS = 5


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill *proc* and every descendant it spawned.

    ``proc.kill()`` alone only terminates the direct child (e.g. latexmk);
    grandchildren (xelatex, biber, pygmentize) survive, keep the stdout/
    stderr pipes open, and the post-kill ``communicate()`` blocks forever
    waiting for EOF on a pipe an orphan still holds (see finding G).
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


class LatexCompilerService:
    """Compile a ``.tex`` entry point to PDF, returning structured results."""

    def __init__(
        self, engine: str = "xelatex", *, guard: BashGuard | None = None, timeout_seconds: int = 300
    ) -> None:
        self._engine = engine
        self._guard = guard or BashGuard()
        self._timeout = timeout_seconds

    @staticmethod
    def toolchain_available(engine: str = "xelatex") -> bool:
        """True if latexmk and the requested engine are on PATH."""
        return bool(shutil.which("latexmk")) and bool(shutil.which(engine))

    @staticmethod
    def locked_preamble_path() -> Path:
        """Absolute path to the tested, locked Greek preamble template."""
        return Path(__file__).resolve().parent / "templates" / "greek_scientific_preamble.tex"

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
        self, project_dir: str | Path, main_tex: str = "main.tex", *, shell_escape: bool = False
    ) -> CompileResult:
        """Compile ``main_tex`` inside ``project_dir`` and return a CompileResult."""
        project = Path(project_dir)
        cmd = self._build_command(main_tex, shell_escape)

        # Route through the safety guard before executing.
        risk, _ = self._guard.evaluate(" ".join(cmd))
        if risk == RiskLevel.BLOCKED:
            return CompileResult(
                ok=False,
                errors=[
                    CompileError(
                        category=CompileErrorCategory.UNKNOWN,
                        message="Compile command blocked by BashGuard",
                        fatal=True,
                    )
                ],
            )

        proc = subprocess.Popen(
            cmd,
            cwd=str(project),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name != "nt"),
        )
        try:
            stdout, _stderr = proc.communicate(timeout=self._timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(proc)
            try:
                stdout, _stderr = proc.communicate(timeout=_DRAIN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # Pipe still won't close (an orphaned grandchild holds it
                # open) — abandon stdout rather than block. The .log file
                # on disk, read below, is parse_log's primary source anyway.
                stdout = ""

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
