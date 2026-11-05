# Long context (40+ tool results)

Each sample forces 40 or more separate tool results into one run, then asks for an answer that
depends on them (a sum, and values from the first and last results). It exercises context
compression (H9) and tool-result trimming (H10): the answer must survive the compaction and the
run must get cheaper. The prompts forbid batching so the result count is the point; a model that
batches anyway scores the same but stresses nothing, so check `metrics.tool_calls` in the output.

`expected_answer` is comma-separated: every part must appear in the final reply.
