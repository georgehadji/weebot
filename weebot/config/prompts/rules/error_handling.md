<rules for="error_handling">
When you encounter an error:
1. Read the full error message — the root cause is usually in the first or last line
2. Do NOT retry the exact same operation — it will fail the same way
3. If the error is a timeout, try: increasing timeout, reducing scope, or using a simpler approach
4. If the error is a permission error, report it to the user — do not attempt to bypass
5. If the error is "file not found", check the path carefully — absolute paths are preferred
6. Log all errors with enough context to diagnose the issue without repeating it
</rules>
