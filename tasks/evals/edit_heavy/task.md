# Edit-heavy refactors

Multi-file edits made in place with `file_editor`: a rename across three files, a signature
change with its callers, and two identical functions edited without ambiguity. The plan's gate for
the edit pipeline (H6) is edit-failure loops at most 0.5x the baseline on this suite.

The agent creates its own fixtures under `Output/evals/edit_heavy/<case>/`, so the scorer reads files, not the
reply. Delete `Output/evals/edit_heavy` before a run so a leftover from an earlier run cannot pass.

`expected_answer` is a JSON spec read by `evaluate.py`: per file, strings it must `has`, strings
it must not (`lacks`), exact occurrence `count`s, and it must still parse as Python.
