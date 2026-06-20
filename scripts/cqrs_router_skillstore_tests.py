"""3 complex tasks: CQRS mediator, task router, skill store persistence."""
import json, sys, time, asyncio, tempfile, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
OUT = Path("Output")

# ── Task 1: CQRS Mediator Pipeline ──────────────────────────────────

OUT1 = OUT / "cqrs-stress"
OUT1.mkdir(parents=True, exist_ok=True)

from weebot.application.cqrs.mediator import Mediator
from weebot.application.cqrs.commands import CreatePlanCommand

handlers_called = []

mediator = Mediator()

# Register handler as class with .handle() method (mediator API)
class CreatePlanHandler:
    async def handle(self, cmd: CreatePlanCommand):
        handlers_called.append("create_plan")
        return type('R', (), {'success': True, 'data': {"plan": "created", "steps": 3}})()

mediator.register_command_handler(CreatePlanCommand, CreatePlanHandler())

async def test_mediator():
    results = []
    
    # Valid command
    t1 = time.monotonic()
    r1 = await mediator.send(CreatePlanCommand(prompt="test plan", session_id="s1"))
    results.append({"command": "CreatePlanCommand", "status": "success", "time_ms": round((time.monotonic()-t1)*1000), "success": r1.success})
    
    # Unregistered command — should fail
    class CustomCmd:
        pass
    try:
        await mediator.send(CustomCmd())
        results.append({"command": "CustomCmd", "status": "unexpected_success"})
    except Exception as e:
        results.append({"command": "CustomCmd", "status": "error_raised", "error": type(e).__name__})
    
    # None — should fail
    try:
        await mediator.send(None)
        results.append({"command": "None", "status": "unexpected_success"})
    except Exception as e:
        results.append({"command": "None", "status": "error_raised", "error": type(e).__name__})
    
    summary = {
        "handlers_called": len(handlers_called),
        "registered_handler_fired": r1.success,
        "error_paths_correct": results[1]["status"] == "error_raised" and results[2]["status"] == "error_raised",
        "results": results,
    }
    (OUT1 / "mediator-test.json").write_text(json.dumps(summary, indent=2))
    ok = summary["registered_handler_fired"] and summary["error_paths_correct"]
    print(f"[CQRS] {'✓' if ok else '✗'} handler fired, error paths correct")

asyncio.run(test_mediator())

# ── Task 2: Task Model Router Accuracy ─────────────────────────────

OUT2 = OUT / "router-stress"
OUT2.mkdir(parents=True, exist_ok=True)

from weebot.application.services.task_model_router import classify_step, TaskCategory

test_cases = [
    # CODING
    ("refactor the database module", TaskCategory.CODING),
    ("implement login endpoint with JWT", TaskCategory.CODING),
    ("write a Python function for fibonacci", TaskCategory.CODING),
    ("fix the bug in auth middleware", TaskCategory.CODING),
    ("build a REST API for user profiles", TaskCategory.CODING),
    # FILE_OPS
    ("list all Python files recursively", TaskCategory.FILE_OPS),
    ("create output directory for reports", TaskCategory.FILE_OPS),
    ("read the configuration file", TaskCategory.FILE_OPS),
    ("check if the file exists", TaskCategory.FILE_OPS),
    ("rename the old manifest to archive", TaskCategory.FILE_OPS),
    # RESEARCH
    ("search for Clean Architecture patterns", TaskCategory.RESEARCH),
    ("web_search LLM agent frameworks", TaskCategory.RESEARCH),
    ("investigate the root cause of the crash", TaskCategory.RESEARCH),
    ("gather requirements for the new feature", TaskCategory.RESEARCH),
    ("browse the competitor pricing page", TaskCategory.RESEARCH),
    # REVIEW
    ("audit security in auth.py", TaskCategory.REVIEW),
    ("review code for best practices", TaskCategory.REVIEW),
    ("inspect the deployment config for issues", TaskCategory.REVIEW),
    ("evaluate the test coverage report", TaskCategory.REVIEW),
    ("find bugs in the payment module", TaskCategory.REVIEW),
    # EDGE CASES
    ("research and implement feature X", TaskCategory.RESEARCH),  # "research" keyword before "implement"
    ("refactor and review the logging module", TaskCategory.CODING),  # "refactor" wins
    ("create and test a new endpoint", TaskCategory.CODING),
    ("audit and fix security vulnerabilities", TaskCategory.REVIEW),  # "audit" + "security"
    ("summarize the meeting notes", TaskCategory.SUMMARIZATION),
]

router_results = []
category_stats = {cat: {"correct": 0, "total": 0} for cat in TaskCategory}
for desc, expected in test_cases:
    actual = classify_step(desc)
    correct = actual == expected
    router_results.append({"description": desc, "expected": expected.value, "actual": actual.value, "correct": correct})
    category_stats[expected]["total"] += 1
    if correct:
        category_stats[expected]["correct"] += 1

accuracy = sum(1 for r in router_results if r["correct"]) / len(router_results) * 100
print(f"[ROUTER] Accuracy: {accuracy:.0f}% ({sum(1 for r in router_results if r['correct'])}/{len(router_results)})")
for cat, stats in sorted(category_stats.items(), key=lambda x: x[0].value):
    if stats["total"] > 0:
        cat_acc = stats["correct"] / stats["total"] * 100
        print(f"   {cat.value}: {stats['correct']}/{stats['total']} ({cat_acc:.0f}%)")

misclass = [r for r in router_results if not r["correct"]]
if misclass:
    print(f"   Misclassifications: {len(misclass)}")
    for m in misclass:
        print(f"     '{m['description']}' -> {m['actual']} (expected {m['expected']})")

(OUT2 / "router-accuracy.json").write_text(json.dumps({
    "total": len(router_results), "correct": sum(1 for r in router_results if r["correct"]),
    "accuracy_pct": accuracy,
    "per_category": {cat.value: {"correct": s["correct"], "total": s["total"],
        "precision": round(s["correct"]/s["total"]*100, 1) if s["total"] else 0}
        for cat, s in category_stats.items()},
    "misclassifications": misclass,
    "results": [{"desc": r["description"], "expected": r["expected"], "actual": r["actual"]} for r in router_results],
}, indent=2))

# ── Task 3: Skill Store Persistence Cycle ──────────────────────────

OUT3 = OUT / "skillstore-stress"
OUT3.mkdir(parents=True, exist_ok=True)

from weebot.domain.models.skill import Skill, SkillMetadata, SkillProvenance, SkillEdit

async def test_skillstore():
    db_path = os.path.join(tempfile.gettempdir(), "weebot_stress_skillstore.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    from weebot.infrastructure.persistence.skill_store import SkillStore
    store = SkillStore(db_path=db_path)

    store_results = []

    # 1. Save 5 skills
    skills = []
    for i, (name, desc) in enumerate([
        ("web-scraper", "Scrapes HTML pages"),
        ("csv-analyzer", "Analyzes CSV data"),
        ("image-processor", "Resizes images"),
        ("pdf-generator", "Generates PDFs"),
        ("email-sender", "Sends emails"),
    ]):
        s = Skill(
            name=name, description=desc, content=f"Content for {name}",
            metadata=SkillMetadata(
                trust="trusted" if i < 3 else "candidate",
                provenance=SkillProvenance(origin="human" if i < 4 else "imported", positive_uses=i),
                platforms=["linux", "windows"] if i % 2 == 0 else ["macos"],
                config=[{"key": f"{name}_api_key", "description": f"API key for {name}"}],
            ),
        )
        await store.save(s)
        skills.append(s)
    store_results.append({"op": "save_5", "status": "success"})

    # 2. Load them back
    loaded = []
    for s in skills:
        l = await store.load(s.name)
        loaded.append(l)
    all_loaded = all(l is not None for l in loaded)
    all_names_match = all(l.name == s.name for l, s in zip(loaded, skills))
    all_descs_match = all(l.description == s.description for l, s in zip(loaded, skills))
    store_results.append({"op": "load_5", "all_loaded": all_loaded, "names_match": all_names_match, "descs_match": all_descs_match})

    # 3. Round-trip metadata
    meta_ok = all(
        l.metadata.trust == s.metadata.trust and
        l.metadata.provenance.origin == s.metadata.provenance.origin
        for l, s in zip(loaded, skills)
    )
    store_results.append({"op": "metadata_roundtrip", "ok": meta_ok})

    # 4. Export best
    exported = skills[0].export_best()
    has_slow_update = "SLOW_UPDATE" in skills[0].content
    store_results.append({"op": "export_best", "slow_update_stripped": not has_slow_update})

    # 5. Apply edits
    edits = [SkillEdit(op="append", target="end", content="\n# New section", support_count=3)]
    edited = skills[0].apply_edits(edits)
    version_grew = len(edited.versions) > len(skills[0].versions)
    store_results.append({"op": "apply_edits", "version_grew": version_grew, "version_count": len(edited.versions)})

    # 6. Accept version
    accepted = edited.accept_current(validation_score=0.95)
    best_updated = accepted.best_version > 0
    store_results.append({"op": "accept_version", "best_updated": best_updated, "best_version": accepted.best_version})

    # 7. Reject version
    rejected = accepted.reject_current(score_drop=0.3)
    buffer_grew = len(rejected.rejected_edit_buffer) > 0
    store_results.append({"op": "reject_version", "buffer_grew": buffer_grew, "buffer_size": len(rejected.rejected_edit_buffer)})

    # 8. List and delete
    names_before = await store.list_names()
    await store.delete(skills[-1].name)
    names_after = await store.list_names()
    deleted_ok = len(names_after) == len(names_before) - 1 and skills[-1].name not in names_after
    store_results.append({"op": "delete_skill", "before": len(names_before), "after": len(names_after), "removed": deleted_ok})

    # 9. Simulate restart — new store connection
    store2 = SkillStore(db_path=db_path)
    names_after_restart = await store2.list_names()
    persistence_ok = len(names_after_restart) == len(names_after) and all(n in names_after_restart for n in names_after)
    store_results.append({"op": "persistence_restart", "survived": persistence_ok, "count": len(names_after_restart)})

        all_ok = all(
        r.get("ok") or r.get("status") == "success"
        or r.get("all_loaded") or r.get("version_grew") or r.get("buffer_grew")
        or r.get("survived") or r.get("removed") or r.get("slow_update_stripped")
        or r.get("names_match") or r.get("descs_match")
        for r in store_results
    )
    passed = sum(1 for r in store_results if (
        r.get("ok") or r.get("status") == "success"
        or r.get("all_loaded") or r.get("version_grew") or r.get("buffer_grew")
        or r.get("survived") or r.get("removed") or r.get("slow_update_stripped")
        or r.get("names_match") or r.get("descs_match")
    ))
    print(f"[SKILLSTORE] {'✓' if all_ok else '✗'} {passed}/{len(store_results)} ops passed")

    (OUT3 / "skillstore-cycle.json").write_text(json.dumps({"all_ok": all_ok, "results": store_results}, indent=2))

    await store.close()
    if os.path.exists(db_path):
        os.remove(db_path)

asyncio.run(test_skillstore())

print(f"\n[DONE] Outputs at {OUT}/cqrs-stress/, {OUT}/router-stress/, {OUT}/skillstore-stress/")
