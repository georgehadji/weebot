# RTK Integration for Weebot - Token Economy

## Overview

This integration adds support for RTK (Rust Token Killer) to the Weebot framework, providing significant token savings when executing commands through the BashTool. RTK filters and compresses command outputs before they reach your LLM context, saving 60-90% of tokens on common operations.

## How It Works

The integration works by:

1. Checking if RTK is available in the system
2. Determining if a command should be optimized with RTK
3. Transforming the command to use RTK equivalents where applicable
4. Executing the command through RTK for token-optimized output
5. Falling back to standard execution if RTK is not available

## Supported Commands

RTK can optimize the following types of commands:

- Git operations (`git status`, `git log`, `git diff`, etc.)
- File system operations (`ls`, `find`, `tree`, etc.)
- Code search (`grep`, `ripgrep`, etc.)
- Build tools (`cargo`, `npm`, `yarn`, `pnpm`, `go build`, etc.)
- Testing frameworks (`pytest`, `vitest`, `cargo test`, etc.)
- Container tools (`docker`, `kubectl`, etc.)
- Code analysis (`eslint`, `ruff`, `tsc`, etc.)

## Benefits

- **Token Savings**: 60-90% reduction in token consumption for common operations
- **Transparency**: Seamless integration with existing workflows
- **Fallback**: Automatic fallback to standard execution if RTK is unavailable
- **Performance**: Minimal overhead (~5-15ms proxy overhead per command)

## Installation

To use RTK with Weebot, install RTK separately:

```bash
# Using cargo
cargo install --git https://github.com/rtk-ai/rtk

# Or using the install script
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
```

## Configuration

The integration is automatic - it will check for RTK availability and use it when beneficial. No additional configuration is required.

## Troubleshooting

- If RTK is installed but not being used, check that it's in your PATH
- Verify RTK installation with: `rtk --version`
- Check RTK functionality with: `rtk gain` (should show token savings stats)

## Architecture

The integration is implemented in:
- `weebot/rtk_integration.py` - Core integration logic
- `weebot/tools/bash_tool.py` - Modified to use RTK when available

The system maintains full backward compatibility - if RTK is not available, commands execute normally through the existing sandboxed executor.