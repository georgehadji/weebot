"""HarnessPromptAssembler — builds the executor system-prompt block from HarnessConfig.

Reads behavioural instruction surfaces (bootstrap, execution, verification,
failure_recovery) from a HarnessConfig and formats them as a structured
markdown block for injection into the executor's system prompt.

This is the bridge between the versioned HarnessConfig YAML and the actual
prompt the LLM sees.  The Self-Harness loop mutates the YAML; this
service ensures those mutations reach the executor.
"""
from __future__ import annotations

from weebot.domain.models.harness_instructions import (
    InstructionConfig,
    RuntimeControlConfig,
    SubagentConfig,
    SkillSelectionConfig,
)


class HarnessPromptAssembler:
    """Assembles the harness instruction block for executor system prompts.

    Usage::

        assembler = HarnessPromptAssembler()
        block = assembler.assemble(instructions=config.instructions)
        # block is a str you concatenate into the executor's system prompt
    """

    BLOCK_TEMPLATE = (
        "\n\n## Harness Instructions (model-specific)\n\n"
        "{bootstrap_section}"
        "{execution_section}"
        "{verification_section}"
        "{failure_recovery_section}"
        "{extension_section}"
    )

    @classmethod
    def assemble(
        cls,
        instructions: InstructionConfig | None = None,
        runtime_control: RuntimeControlConfig | None = None,
        subagents: SubagentConfig | None = None,
        skill_selection: SkillSelectionConfig | None = None,
    ) -> str:
        """Build a harness instruction block for system-prompt injection.

        Args:
            instructions: Behavioural instruction surfaces to include.
                When None, the entire block is omitted.
            runtime_control: Runtime policy knobs (not injected into prompt
                directly — used by flow logic; included here as comment).
            subagents: Subagent declarations (reserved for future use).
            skill_selection: Active skill names (reserved for future use).

        Returns:
            A formatted markdown block, or empty string when instructions
            is None or all fields are empty.
        """
        if instructions is None:
            return ""

        parts = []

        if instructions.bootstrap:
            parts.append(f"**Boot:** {instructions.bootstrap}")

        if instructions.execution:
            parts.append(f"**Execute:** {instructions.execution}")

        if instructions.verification:
            parts.append(f"**Verify:** {instructions.verification}")

        if instructions.failure_recovery:
            parts.append(f"**Recover:** {instructions.failure_recovery}")

        if instructions.system_prompt_extension:
            parts.append(instructions.system_prompt_extension)

        if not parts:
            return ""

        return cls.BLOCK_TEMPLATE.format(
            bootstrap_section=f"- {parts[0]}\n" if len(parts) > 0 else "",
            execution_section=f"- {parts[1]}\n" if len(parts) > 1 else "",
            verification_section=f"- {parts[2]}\n" if len(parts) > 2 else "",
            failure_recovery_section=f"- {parts[3]}\n" if len(parts) > 3 else "",
            extension_section=f"{parts[4]}\n" if len(parts) > 4 else "",
        )

    @classmethod
    def assemble_compact(
        cls,
        instructions: InstructionConfig | None = None,
    ) -> str:
        """Return a single-line summary of active harness instructions.

        Useful for logging / debugging / audit trails.
        """
        if instructions is None:
            return "harness: none"

        active = []
        if instructions.bootstrap:
            active.append("bootstrap")
        if instructions.execution:
            active.append("execution")
        if instructions.verification:
            active.append("verification")
        if instructions.failure_recovery:
            active.append("failure_recovery")
        if instructions.system_prompt_extension:
            active.append("extension")

        return f"harness: {', '.join(active) if active else 'none'}"
