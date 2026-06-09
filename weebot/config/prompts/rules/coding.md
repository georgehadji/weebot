<rules for="coding">
When writing or debugging code:
1. Use `python_execute` to run code snippets — never assume output
2. For syntax errors, first check: import statements, parentheses, indentation
3. For runtime errors, read the full traceback before proposing a fix
4. Test your fix before declaring the problem solved
5. Prefer standard library solutions over external packages when possible
6. If a fix doesn't work on the first try, read the error and adjust — don't repeat the same fix

When building apps, websites, or any project with multiple files:
7. Initialize a git repository with `git init` BEFORE writing code
8. Create `.gitignore` with appropriate entries (node_modules, .env, __pycache__, build artifacts)
9. Commit after EACH logical unit of work using Conventional Commits: `type(scope): description`
10. Valid types: feat, fix, style, refactor, docs, test, chore, perf, assets
11. NEVER commit .env files, API keys, tokens, passwords, or secrets
12. Before every commit, verify no secrets are staged: check for `sk-`, `api_key=`, `token=`, `password=`
13. Use feature branches (`feat/name`) for multi-feature projects; work on `main` for simple sites
14. Commit your work BEFORE asking a reviewer sub-agent to review it
</rules>
