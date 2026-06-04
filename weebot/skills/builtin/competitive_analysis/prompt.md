---
name: competitive_analysis
description: Analyze a competitive landscape using swarm research, clustering,
             and whitespace identification. Based on proven patterns from
             agent swarm research methodology.
metadata:
  emoji: 🔬
---

# Competitive Landscape Analysis

When asked to research a competitive landscape, market position, or content
strategy for a channel/product:

## Phase 1: Discovery (use `swarm` tool)

1. Decompose the research question with `swarm(prompt="...")`
2. Let the goal agent determine sub-goals automatically — do NOT manually
   list competitors or categories. The swarm is better at discovering
   unexpected competitors than you are.
3. Target: direct competitors, adjacent players, aspirational benchmarks

## Phase 2: Clustering

After the swarm returns:
1. Group competitors by positioning: price tier, target audience, content style,
   geography, channel size
2. For each cluster, extract:
   - Common patterns (what does EVERYONE in this cluster do?)
   - Differentiation strategies (what makes the top player in each cluster stand out?)
3. Flag: oversaturated segments (too many similar players) and underserved niches
   (gaps in the market)

## Phase 3: Whitespace Identification

Cross-reference the clusters to find opportunity:
1. **Table stakes** — what's EVERYONE doing? (Must also provide this, but not differentiation)
2. **Whitespace** — what's NOBODY doing? (Highest potential, highest risk)
3. **Validated whitespace** — what's ONE player doing successfully that others aren't?
   (Lower risk — proof of demand exists)

## Phase 4: Recommendations

For each whitespace opportunity:
1. **Effort** (1-5): How hard to execute?
2. **Moat potential** (1-5): How defensible once established?
3. **Time-to-value** (1-5): How quickly can results be seen?
4. **Concrete next action**: A specific first step

## Output Format

Always produce:
1. **Executive summary** — 3 sentences max
2. **Competitor cluster map** — markdown table with columns:
   | Cluster | Players | Common Patterns | Top Differentiator |
3. **Whitespace matrix** — markdown table with columns:
   | Opportunity | Effort | Moat | TTV | First Action |
4. **Actionable recommendations** — numbered list, ordered by effort×moat score

## Anti-patterns

- Do NOT manually list competitors before running the swarm — the swarm finds
  competitors you would miss
- Do NOT produce a single monolithic report — always break into phases
- Do NOT skip the whitespace matrix — that's the actionable output
- Do NOT recommend copying what everyone else does — find gaps
