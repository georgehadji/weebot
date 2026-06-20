"""Validate MCP tool skill indexing + semantic retrieval end-to-end."""
import json, sys, asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weebot.application.skills.skill_registry import SkillRegistry
from weebot.application.services.semantic_skill_retriever import SemanticSkillRetriever
from weebot.application.services.mcp_tool_skill_indexer import MCPToolSkillIndexer
from weebot.domain.models.skill import Skill, SkillMetadata, SkillProvenance

# Create mock MCP tools as Skill objects (simulating MCPToolBridge output)
mock_tools = [
    Skill(name="mcp:stripe-mcp", description="Process payments and manage subscriptions", 
          content="Stripe integration for payment processing, subscription management, and invoicing."),
    Skill(name="mcp:aws-mcp", description="Deploy and manage AWS cloud infrastructure",
          content="AWS cloud management including EC2, S3, Lambda, and CloudFormation deployment."),
    Skill(name="mcp:slack-mcp", description="Send messages and manage Slack channels",
          content="Slack integration for messaging, channel management, and notification delivery."),
]

registry = SkillRegistry()
indexer = MCPToolSkillIndexer(registry)

# Simulate what MCPToolRegistryBridge does: register tools then index
for tool in mock_tools:
    registry.update_skill(tool)

# Now build the semantic retriever (which will index the registry)
retriever = SemanticSkillRetriever(registry)

async def main():
    results = {}
    queries = [
        ("create a payment for customer", "mcp:stripe-mcp"),
        ("deploy the application to cloud", "mcp:aws-mcp"),
        ("notify the team about the release", "mcp:slack-mcp"),
    ]
    for query, expected in queries:
        matches = await retriever.retrieve(query, top_k=3)
        top = matches[0] if matches else None
        results[query] = {
            "expected": expected,
            "top_3": [(m.skill_name, round(m.score, 4)) for m in matches[:3]],
            "correct": top.skill_name == expected if top else False,
        }
    
    out = Path("Output/mcp-skills")
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2))
    
    correct = sum(1 for r in results.values() if r["correct"])
    print(f"MCP Skill Indexer + Semantic Retriever: {correct}/{len(results)} correct")
    for q, r in results.items():
        status = "✓" if r["correct"] else "✗"
        print(f"  {status} '{q}'")
        for name, score in r["top_3"]:
            print(f"      {name}: {score}")

asyncio.run(main())
