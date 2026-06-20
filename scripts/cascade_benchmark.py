"""Cascade benchmark — compare all 4 Tier models on the same prompt."""
import asyncio, json, time, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weebot.application.di import Container
from weebot.application.ports.llm_port import LLMPort

PROMPT = "Write a Python function that computes fibonacci recursively."

MODELS = {
    "Tier 1 (GLM 5.2)": "z-ai/glm-5.2",
    "Tier 2 (DeepSeek V4 Flash)": "deepseek/deepseek-v4-flash",
    "Tier 3 (Kimi K2.6)": "moonshotai/kimi-k2.6",
    "Tier 4 (Qwen 3.7 Max)": "qwen/qwen3.7-max",
}

async def main():
    container = Container()
    container.configure_defaults()
    llm = container.get(LLMPort)
    
    results = []
    for label, model in MODELS.items():
        print(f"Benchmarking {label}...", end=" ", flush=True)
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                llm.chat(
                    messages=[{"role": "user", "content": PROMPT}],
                    model=model,
                    temperature=0.1,
                    max_tokens=500,
                ),
                timeout=60.0,
            )
            elapsed = time.monotonic() - start
            output = response.content or ""
            # Quick correctness check: must contain 'def fib' and 'return'
            correct = "def fib" in output.lower() and "return" in output
            results.append({
                "model": label,
                "model_id": model,
                "latency_s": round(elapsed, 2),
                "output_length": len(output),
                "correct": correct,
                "output_preview": output[:200],
            })
            print(f"{elapsed:.1f}s, {len(output)} chars, {'✓' if correct else '✗'}")
        except asyncio.TimeoutError:
            results.append({"model": label, "model_id": model, "latency_s": 60.0, "output_length": 0, "correct": False, "output_preview": "TIMEOUT"})
            print("TIMEOUT")
        except Exception as exc:
            results.append({"model": label, "model_id": model, "latency_s": 0, "output_length": 0, "correct": False, "output_preview": str(exc)[:200]})
            print(f"ERROR: {exc}")

    out = Path("Output/cascade-test")
    out.mkdir(exist_ok=True)
    (out / "benchmark-results.json").write_text(json.dumps(results, indent=2))
    
    md = ["# Cascade Benchmark Results", "", f"**Prompt:** `{PROMPT}`", "", "| Model | Latency | Output | Correct |", "|-------|---------|--------|---------|"]
    for r in results:
        md.append(f"| {r['model']} | {r['latency_s']}s | {r['output_length']} chars | {'✓' if r['correct'] else '✗'} |")
    (out / "benchmark-results.md").write_text("\n".join(md))
    
    print(f"\nResults written to Output/cascade-test/")

asyncio.run(main())
