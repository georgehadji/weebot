# Local models with Ollama

Weebot can send selected roles to a model served by your own Ollama. It is **off by default**:
with `OLLAMA_ENABLED` unset, routing, the catalog and every role cascade are unchanged.

## Turn it on

1. `ollama pull qwen3:8b` (check the tag with `ollama list`).
2. Ollama's `/v1` endpoint ignores a per-request `num_ctx`, so the model keeps a 4096-token
   context and silently truncates Weebot's prompts. Build a derived model once:
   `ollama create qwen3-weebot -f deploy/ollama/Modelfile`
3. In `.env`:
   ```
   OLLAMA_ENABLED=true
   OLLAMA_MODEL=qwen3-weebot
   OLLAMA_CONTEXT_WINDOW=16384
   OLLAMA_ROLES=summarizer,documentation
   ```
   `OLLAMA_CONTEXT_WINDOW` must equal the Modelfile's `num_ctx`: Weebot budgets against it.

## Using two models: local and cloud

`OLLAMA_ROLES` takes `role` (uses `OLLAMA_MODEL`) or `role=tag`, so one local model and one
Ollama cloud model can serve different roles:

```
OLLAMA_MODEL=qwen3-weebot
OLLAMA_ROLES=summarizer,documentation,verifier=gemma4:31b-cloud,subagent=gemma4:31b-cloud
```

- `qwen3-weebot` runs on your GPU: free, private, small.
- A tag ending in `-cloud` runs on **Ollama's servers**: prompts leave your machine, and it
  uses your Ollama plan's quota (GPU time; 5-hour and weekly limits), not a per-token price.
  Run `ollama signin` once, then `ollama pull gemma4:31b-cloud`. The catalog gives it a 256K
  context and tier STANDARD; no Modelfile or `OLLAMA_CONTEXT_WINDOW` applies to it.
- Keep content you would not send to a cloud provider on the local model's roles only.
- If the quota is spent or the call fails, the cascade moves on to the normal cloud models.

## What happens

- The local model is `ollama/<OLLAMA_MODEL>` in the catalog (`config/local_models.py`): cost 0,
  tier `LOCAL`.
- For each role in `OLLAMA_ROLES` it is tried **first**; the normal cloud cascade stays behind
  it. If the server is stopped, fails, or has not answered in 20 s (the cascade's hedge delay),
  the cloud models run as before.
- `LocalModelRouter` (`infrastructure/adapters/llm/local_router_adapter.py`) sends `ollama/...`
  ids to `OLLAMA_BASE_URL`; everything else goes where it went before.
- The cascade's low-credit filter never drops the local model.

## Which model, which role

Local `qwen3:8b`: bulk text work only, `summarizer` and `documentation`. A small model fails
at the tool loop and structured JSON.

Cloud `gemma4:31b-cloud` (Ollama's page: Tau2 76.9, LiveCodeBench v6 80.0, 256K context,
native function calling): a candidate for `verifier`, `subagent` and `reviewer`. Those roles
were chosen by Weebot's billed evals (`tasks/audits/model_routing_2026_10_23.md`), so measure
it on your tasks before moving `planner`, `coder` or `executor` onto it; the cascade falls
back to the current models whenever it fails.

Size against your GPU: a 4-bit model needs about its file size in VRAM. `qwen3:8b` (5.2 GB)
fits an 8 GB GPU with room for a 16k context. A 31B model (about 20 GB) does not: most layers
run on the CPU, generation drops to a few tokens per second, and it can miss the cascade's
timeouts. Use a larger model only on a GPU with enough VRAM, or for offline batch jobs.
