"""Dependency graph analysis for all weebot modules — single pass."""
import ast, json, sys, os
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weebot.core.layer_classifier import layer_for_module

ROOT = Path("weebot")
COLORS = {"domain": "#22c55e", "application": "#3b82f6", "infrastructure": "#f97316",
          "interfaces": "#ef4444", "core": "#a855f7", "unknown": "#94a3b8"}
ALLOWED = {"domain": set(), "application": {"domain", "core"},
           "infrastructure": {"domain", "application", "core"},
           "interfaces": {"domain", "application", "core", "infrastructure"}, "core": set()}

files = sorted(ROOT.rglob("*.py"))
files = [f for f in files if "GitNexus" not in str(f)]
print(f"Found {len(files)} Python files (excluding GitNexus)")

nodes = {}  # rel_path -> {"id": str, "label": str, "layer": str, "color": str, "in_degree": int, "out_degree": int}
edges = []
violations = []
layer_counts = defaultdict(int)
cross_layer = defaultdict(lambda: defaultdict(int))

for fp in files:
    rel = str(fp).replace("\\", "/")
    layer = layer_for_module(rel)
    layer_counts[layer] += 1
    node_id = rel.replace("/", ".").removesuffix(".py")
    nodes[rel] = {"id": node_id, "label": Path(rel).stem, "layer": layer,
                  "color": COLORS.get(layer, "#94a3b8"), "in_degree": 0, "out_degree": 0}

for fp in files:
    rel = str(fp).replace("\\", "/")
    src_layer = layer_for_module(rel)
    try:
        tree = ast.parse(fp.read_text(encoding="utf-8"))
    except Exception:
        continue
    
    for node in ast.walk(tree):
        imported = None
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("weebot"):
            imported = node.module.replace(".", "/") + ".py"
            if node.level > 0:
                pkg = rel.rsplit("/", 1)[0]
                imported = pkg + "/" + imported
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("weebot"):
                    imported = alias.name.replace(".", "/") + ".py"
        
        if imported and imported in nodes:
            tgt_layer = layer_for_module(imported)
            nodes[rel]["out_degree"] += 1
            nodes[imported]["in_degree"] += 1
            edges.append({"source": nodes[rel]["id"], "target": nodes[imported]["id"],
                         "source_layer": src_layer, "target_layer": tgt_layer})
            cross_layer[src_layer][tgt_layer] += 1
            if tgt_layer not in ALLOWED.get(src_layer, set()) and tgt_layer != src_layer:
                violations.append({"source": rel, "target": imported, "src_layer": src_layer, "tgt_layer": tgt_layer})

out = Path("Output/deps-v3")
out.mkdir(exist_ok=True)

# layer-report.md
lines = ["# Layer Analysis Report", "", f"**Modules:** {len(files)} | **Edges:** {len(edges)} | **Violations:** {len(violations)}", ""]
lines += ["## Per-Layer Counts", "| Layer | Count | % |", "|-------|-------|---|"]
for lyr, cnt in sorted(layer_counts.items(), key=lambda x: -x[1]):
    lines.append(f"| {lyr} | {cnt} | {cnt/len(files)*100:.1f}% |")

lines += ["", "## Cross-Layer Edge Matrix", "| Src \\ Tgt | " + " | ".join(sorted(COLORS)) + " |"]
lines += ["|---" * (len(COLORS)+1) + "|"]
for sl in sorted(COLORS):
    row = [str(cross_layer[sl].get(tl, 0)) for tl in sorted(COLORS)]
    lines.append(f"| {sl} | " + " | ".join(row) + " |")

lines += ["", "## Top 20 Most-Imported Modules", "| Module | Layer | In-Degree |", "|--------|-------|-----------|"]
top = sorted(nodes.values(), key=lambda n: -n["in_degree"])[:20]
for n in top:
    lines.append(f"| {n['id']} | {n['layer']} | {n['in_degree']} |")

lines += ["", "## Architecture Violations", ""]
for v in sorted(violations, key=lambda x: x["source"])[:30]:
    lines.append(f"- **{v['source']}** ({v['src_layer']}) → `{v['target']}` ({v['tgt_layer']}) [VIOLATION]")
if len(violations) > 30:
    lines.append(f"\n*...and {len(violations)-30} more*")

(out / "layer-report.md").write_text("\n".join(lines), encoding="utf-8")

# dependency-graph.json
(out / "dependency-graph.json").write_text(json.dumps({
    "nodes": list(nodes.values()), "edges": edges,
    "stats": {"total_modules": len(files), "total_edges": len(edges),
              "layer_counts": dict(layer_counts), "cross_layer_edges": len(edges),
              "violations": len(violations)}
}, indent=2), encoding="utf-8")

# dependency-graph.html
nodes_json = json.dumps(list(nodes.values()))
edges_json = json.dumps(edges)
colors_json = json.dumps(COLORS)
html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Weebot Dependency Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script><style>body{{margin:0;overflow:hidden;font-family:system-ui}}
.node{{stroke:#fff;stroke-width:1.5}} .node:hover{{stroke:#000;stroke-width:3}}
.link{{stroke:#999;stroke-opacity:0.3}} .tooltip{{position:absolute;background:#222;color:#fff;padding:6px 10px;border-radius:4px;font-size:12px;pointer-events:none;max-width:300px}}</style></head><body>
<div class="tooltip" style="opacity:0"></div>
<script>
const nodes={nodes_json};
const edges={edges_json};
const colors={colors_json};
const w=window.innerWidth,h=window.innerHeight;
const svg=d3.select("body").append("svg").attr("width",w).attr("height",h);
const tooltip=d3.select(".tooltip");
const sim=d3.forceSimulation(nodes).force("link",d3.forceLink(edges).id(d=>d.id).distance(60))
 .force("charge",d3.forceManyBody().strength(-80)).force("center",d3.forceCenter(w/2,h/2))
 .force("collide",d3.forceCollide(8));
const link=svg.append("g").selectAll("line").data(edges).join("line").attr("class","link");
const node=svg.append("g").selectAll("circle").data(nodes).join("circle").attr("class","node")
 .attr("r",d=>Math.sqrt(d.in_degree+1)*3).attr("fill",d=>d.color)
 .on("mouseover",(ev,d)=>{{tooltip.style("opacity",1).html(`<b>${{d.id}}</b><br>Layer: ${{d.layer}}<br>In: ${{d.in_degree}} Out: ${{d.out_degree}}`)
  .style("left",(ev.pageX+10)+"px").style("top",(ev.pageY-20)+"px")}})
 .on("mousemove",ev=>{{tooltip.style("left",(ev.pageX+10)+"px").style("top",(ev.pageY-20)+"px")}})
 .on("mouseout",()=>{{tooltip.style("opacity",0)}})
 .call(d3.drag().on("start",(ev,d)=>{{if(!ev.active)sim.alphaTarget(0.3).restart();d.fx=d.x;d.fy=d.y}})
  .on("drag",(ev,d)=>{{d.fx=ev.x;d.fy=ev.y}})
  .on("end",(ev,d)=>{{if(!ev.active)sim.alphaTarget(0);d.fx=null;d.fy=null}}));
sim.on("tick",()=>{{link.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y).attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);
 node.attr("cx",d=>d.x).attr("cy",d=>d.y)}});
</script></body></html>"""
(out / "dependency-graph.html").write_text(html, encoding="utf-8")

print(f"Done. {len(files)} modules, {len(edges)} edges, {len(violations)} violations.")
print(f"Layers: {dict(layer_counts)}")
print(f"Top 5 by in-degree: {[(n['id'],n['in_degree']) for n in sorted(nodes.values(),key=lambda x:-x['in_degree'])[:5]]}")
