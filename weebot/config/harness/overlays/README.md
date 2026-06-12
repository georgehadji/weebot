# Harness Config Overlays

Model-specific instruction overrides for the Self-Harness system.

## Format

Each overlay YAML file contains ONLY the fields that differ from the base
harness config.  The ``ModelAwareHarnessResolver`` merges the overlay into
the active ``HarnessConfig`` at runtime.

```yaml
# weebot/config/harness/overlays/gpt-4o.yaml
model_pattern: "gpt-4o*"
instructions:
  bootstrap: "Start by analyzing the workspace structure with tree/walk commands."
  execution: "Write complete, tested solutions. Verify with unit tests."
  verification: "Run the test suite and any lint checks before concluding."
  failure_recovery: "If a command fails, check the error message and try an alternative approach."
```

## Naming Convention

Overlay files are named by model ID pattern::

    {model_family}-{variant}.yaml

Examples:
  - ``gpt-4o.yaml`` — matches all ``gpt-4o*`` models
  - ``qwen3.yaml`` — matches all ``qwen/qwen3*`` models
  - ``claude-sonnet.yaml`` — matches ``claude-sonnet*`` models

## Priority

When multiple patterns match, the most specific one wins (longest pattern
match).  If no pattern matches, the base ``HarnessConfig`` is returned
unchanged.
