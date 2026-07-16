"""Run the OSWorld benchmark with weebot as the agent.

This mirrors OSWorld's ``run.py`` but swaps in :class:`WeebotOSWorldAgent`.
It requires a checkout of the OSWorld repository (for ``desktop_env`` and
``lib_run_single``) and a provisioned VM provider (vmware / virtualbox /
docker / aws / ...). Point ``OSWORLD_HOME`` at the OSWorld checkout, e.g.:

    export OSWORLD_HOME=/path/to/OSWorld
    export OPENROUTER_API_KEY=...        # or OPENAI_API_KEY
    python -m weebot.osworld.run_benchmark \
        --provider_name vmware --model openai/gpt-4o \
        --domain chrome --max_steps 15

Use ``--domain all`` (default) for the full suite, or a single domain
(e.g. ``chrome``, ``libreoffice_calc``) for a quick smoke run.

The VM and evaluation are heavy and cannot run in CI — this script is the
operator-facing entry point, validated end-to-end by the user on a host with
a configured provider. The agent contract itself is covered by unit tests.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("desktopenv.experiment")


def _bootstrap_osworld_path() -> Path:
    """Add the OSWorld checkout to sys.path so its modules import.

    Resolution order: ``--osworld_home`` (parsed later) is not yet available
    here, so we rely on the ``OSWORLD_HOME`` env var. The caller may also have
    OSWorld already installed on the path.
    """
    home = os.getenv("OSWORLD_HOME")
    if home:
        home_path = Path(home).expanduser().resolve()
        if not home_path.exists():
            raise SystemExit(f"OSWORLD_HOME does not exist: {home_path}")
        if str(home_path) not in sys.path:
            sys.path.insert(0, str(home_path))
        return home_path
    # Fall back to import resolution (OSWorld installed as a package).
    return Path.cwd()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OSWorld with the weebot agent")

    # Environment / provider.
    parser.add_argument("--provider_name", type=str, default="vmware",
                        help="vmware, virtualbox, docker, aws, azure, gcp")
    parser.add_argument("--path_to_vm", type=str, default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--screen_width", type=int, default=1920)
    parser.add_argument("--screen_height", type=int, default=1080)
    parser.add_argument("--sleep_after_execution", type=float, default=1.0)
    parser.add_argument("--max_steps", type=int, default=15)
    parser.add_argument("--observation_type",
                        choices=["screenshot", "a11y_tree", "screenshot_a11y_tree", "som"],
                        default="screenshot_a11y_tree")

    # Agent / model.
    parser.add_argument("--model", type=str, default="openai/gpt-4o")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top_p", type=float, default=0.9)
    parser.add_argument("--max_tokens", type=int, default=1500)
    parser.add_argument("--max_trajectory_length", type=int, default=3)

    # Examples / results.
    parser.add_argument("--test_config_base_dir", type=str, default="evaluation_examples")
    parser.add_argument("--test_all_meta_path", type=str,
                        default="evaluation_examples/test_all.json")
    parser.add_argument("--domain", type=str, default="all")
    parser.add_argument("--result_dir", type=str, default="./results")
    parser.add_argument("--osworld_home", type=str, default=None,
                        help="OSWorld checkout dir (overrides OSWORLD_HOME)")

    return parser.parse_args()


def _resolve_meta_paths(args: argparse.Namespace, osworld_home: Path) -> tuple[Path, Path]:
    """Resolve config base dir and meta file relative to the OSWorld checkout."""
    base = Path(args.test_config_base_dir)
    if not base.is_absolute():
        base = osworld_home / base
    meta = Path(args.test_all_meta_path)
    if not meta.is_absolute():
        meta = osworld_home / meta
    return base, meta


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    args = parse_args()

    if args.osworld_home:
        os.environ["OSWORLD_HOME"] = args.osworld_home
    osworld_home = _bootstrap_osworld_path()

    # Imports deferred until after sys.path bootstrap.
    import lib_run_single
    from desktop_env.desktop_env import DesktopEnv

    from weebot.osworld.agent_adapter import WeebotOSWorldAgent

    config_base, meta_path = _resolve_meta_paths(args, osworld_home)
    with open(meta_path, "r", encoding="utf-8") as f:
        test_all_meta = json.load(f)

    if args.domain != "all":
        if args.domain not in test_all_meta:
            raise SystemExit(
                f"Domain {args.domain!r} not in meta. Available: "
                f"{', '.join(sorted(test_all_meta))}"
            )
        test_all_meta = {args.domain: test_all_meta[args.domain]}

    agent = WeebotOSWorldAgent(
        model=args.model,
        max_tokens=args.max_tokens,
        top_p=args.top_p,
        temperature=args.temperature,
        action_space="pyautogui",
        observation_type=args.observation_type,
        max_trajectory_length=args.max_trajectory_length,
    )

    env = DesktopEnv(
        provider_name=args.provider_name,
        path_to_vm=args.path_to_vm,
        action_space=agent.action_space,
        screen_size=(args.screen_width, args.screen_height),
        headless=args.headless,
        os_type="Ubuntu",
        require_a11y_tree=args.observation_type
        in ["a11y_tree", "screenshot_a11y_tree", "som"],
    )

    scores: list[float] = []
    try:
        for domain, example_ids in test_all_meta.items():
            for example_id in example_ids:
                config_file = config_base / "examples" / domain / f"{example_id}.json"
                with open(config_file, "r", encoding="utf-8") as f:
                    example = json.load(f)

                instruction = example["instruction"]
                logger.info("[Domain] %s  [Example] %s", domain, example_id)
                logger.info("[Instruction] %s", instruction)

                example_result_dir = os.path.join(
                    args.result_dir, "pyautogui", args.observation_type,
                    args.model.replace("/", "_"), domain, example_id,
                )
                os.makedirs(example_result_dir, exist_ok=True)

                try:
                    lib_run_single.run_single_example(
                        agent, env, example, args.max_steps, instruction,
                        args, example_result_dir, scores,
                    )
                except Exception as exc:  # noqa: BLE001 — match OSWorld run.py resilience
                    logger.error("Exception in %s/%s: %s", domain, example_id, exc)
                    with open(os.path.join(example_result_dir, "traj.jsonl"), "a") as f:
                        f.write(json.dumps({"Error": f"{domain}/{example_id}: {exc}"}) + "\n")
    finally:
        env.close()

    avg = sum(scores) / len(scores) if scores else 0.0
    logger.info("Average score over %d examples: %.4f", len(scores), avg)
    print(f"\nOSWorld average score: {avg:.4f}  ({len(scores)} examples)")


if __name__ == "__main__":
    main()
