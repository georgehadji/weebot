"""Evaluation framework for agent outputs.

Provides EvalRunner (orchestrates tasks → targets → judges → scores),
and judge implementations (ModelJudge, ScoreJudge).
"""
from weebot.application.eval.eval_runner import EvalRunner, EvalTask, EvalResult, EvalReport
from weebot.application.eval.judges import ModelJudge, ScoreJudge
