"""Validate SemanticSkillRetriever — verify query relevance ordering."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weebot.application.skills.skill_registry import SkillRegistry
from weebot.application.services.semantic_skill_retriever import SemanticSkillRetriever
from weebot.domain.models.skill import Skill

# Create mock registry with 3 distinguishable skills
registry = SkillRegistry()
registry._skills = {
    "weather": Skill(name="weather", description="Weather forecasting and meteorological data retrieval", content="Get temperature, humidity, wind speed, and precipitation forecasts for any location worldwide."),
    "finance": Skill(name="finance", description="Financial data and stock market analysis", content="Retrieve stock prices, market indices, portfolio performance, and financial news from global markets."),
    "sports": Skill(name="sports", description="Sports scores and statistics", content="Get live scores, player stats, team rankings, and game schedules for major sports leagues."),
}

retriever = SemanticSkillRetriever(registry)

async def main():
    results = {}
    queries = [
        ("stock market update", "finance"),
        ("rain forecast for tomorrow", "weather"),
        ("basketball scores last night", "sports"),
    ]
    for query, expected in queries:
        matches = await retriever.retrieve(query, top_k=1)
        top = matches[0] if matches else None
        results[query] = {
            "expected": expected,
            "got": top.skill_name if top else None,
            "score": round(top.score, 4) if top else 0.0,
            "correct": top.skill_name == expected if top else False,
        }
    
    out = Path("Output/embed-test")
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2))
    
    correct = sum(1 for r in results.values() if r["correct"])
    print(f"SemanticSkillRetriever validation: {correct}/{len(results)} correct")
    for q, r in results.items():
        status = "✓" if r["correct"] else "✗"
        print(f"  {status} '{q}' → {r['got']} (expected {r['expected']}, score={r['score']})")

import asyncio
asyncio.run(main())
