<rules for="file_ops">
When working with files:
1. Always use absolute paths within the workspace — never relative paths
2. Before creating a file, check if it already exists with `file_editor(command='view')`
3. View a file before you edit it; a file you have not viewed, or that changed since, is refused.
   For `str_replace`, copy old_str from the file content and make it unique (add surrounding
   lines if it matches twice). Use `patch` for several edits to one file: all apply or none do
4. After editing a file, verify the change with `file_editor(command='view')`
5. When creating multiple files, do them one at a time and verify each before moving on
6. Binary files (.png, .jpg, .exe) cannot be viewed or edited — skip them
</rules>
