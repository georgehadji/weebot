"""Benchmark engine — suite-based model quality evaluation.

Usage::

    from weebot.infrastructure.benchmark.runner import BenchmarkRunner
    from weebot.infrastructure.benchmark.suites import ALL_SUITES

    runner = BenchmarkRunner(call_llm=my_llm_fn)
    profile = await runner.run("deepseek/deepseek-v4-flash")
    print(profile.axes)  # {CapabilityAxis.CODING: 8.5, ...}
"""
