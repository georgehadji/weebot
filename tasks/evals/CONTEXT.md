# tasks/evals/ — benchmark tasks (factory, reused every run)

One folder per task. These are inputs; nothing here records results.

## Reads (each task folder)

- `task.md`: the instruction the agent gets.
- `samples.json`: a list of `{"prompt": "...", "expected_answer": "..."}`.
- `evaluate.py` (optional): `evaluate(session, expected_answer) -> float`, a custom scorer. Without it the harness compares to `expected_answer`.

Loaded by `weebot/application/harness/loader.py` (`TaskLoader.load_all_from_dir` takes every subfolder that has a `task.md`).

## Runs

- All tasks: `python -m cli.main benchmark batch tasks/evals` (results go to `--output`, default `benchmark_results.json`).
- List them: `python -m cli.main benchmark list tasks/evals`.
- The browser, email and LinkedIn groups also have runners: `scripts/run_browser_tasks.py`, `scripts/run_email_tasks.py`, `scripts/run_linkedin_tasks.py` (`--dry-run` prints the prompts).

## What passes

A sample passes when its score is at least `pass_threshold`, 0.5 by default (`weebot/domain/models/benchmark_task.py:36`; the loader does not set it per task). `TaskScorer` (`weebot/application/harness/scorer.py:1-9`) scores in this order: the task's `evaluate.py`; with no `expected_answer`, the session status (completed 1.0, failed 0.0, anything else 0.5); an exact match with the last assistant message (1.0); otherwise word overlap (Jaccard) between the two. So without `evaluate.py` a loose paraphrase can pass at 0.5: write an `evaluate.py` for any task where that is too lenient.

## Human check

Read the scores in the output file. Browser, email and LinkedIn tasks reach real services: run them only with test accounts.

## Adding a task

Copy an existing folder (`sample_math/` is the smallest), then edit `task.md` and `samples.json`.
