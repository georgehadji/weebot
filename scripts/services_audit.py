"""Services audit — runs weebot/core/layer_classifier.py on 103 service files."""
import ast, json, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weebot.core.layer_classifier import layer_for_module

services_dir = Path("weebot/application/services")
files = sorted(services_dir.rglob("*.py"))
print(f"Found {len(files)} Python files")

ALLOWED = {
    "domain": set(),
    "application": {"domain", "core"},
    "infrastructure": {"domain", "application", "core"},
    "interfaces": {"domain", "application", "core", "infrastructure"},
    "core": set(),
    "unknown": set(),
}

violations = []
long_funcs = []
missing_types = []

for fp in files:
    try:
        content = fp.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception:
        continue

    rel = str(fp).replace("\\", "/")
    src_layer = layer_for_module(rel)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # Skip stdlib and third-party imports
            if not node.module.startswith("weebot"):
                continue
            imported = node.module.replace(".", "/")
            tgt_layer = layer_for_module(imported)
            if tgt_layer not in ALLOWED.get(src_layer, set()) and tgt_layer != src_layer:
                violations.append({"file": rel, "import": imported, "src": src_layer, "tgt": tgt_layer})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("weebot"):
                    continue
                imported = alias.name.replace(".", "/")
                tgt_layer = layer_for_module(imported)
                if tgt_layer not in ALLOWED.get(src_layer, set()) and tgt_layer != src_layer:
                    violations.append({"file": rel, "import": imported, "src": src_layer, "tgt": tgt_layer})

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno or 0
            start = node.lineno
            if end - start > 80:
                long_funcs.append({"file": rel, "function": node.name, "lines": end - start})
            has_return = node.returns is not None
            has_args = all(
                a.annotation is not None
                for a in node.args.args
                if a.arg != "self" and a.arg != "cls"
            )
            if not (has_return and has_args):
                missing_types.append({"file": rel, "function": node.name})

out = Path("Output/refactor")
out.mkdir(exist_ok=True)

lines = [
    "# Services Audit Report", "",
    f"**Files analyzed:** {len(files)}",
    f"**Import violations:** {len(violations)}",
    f"**Functions over 80 lines:** {len(long_funcs)}",
    f"**Missing type annotations:** {len(missing_types)}", "",
    "## Import Violations", "",
]
for v in sorted(violations, key=lambda x: x["file"])[:50]:
    lines.append(f'- **{v["file"]}** ({v["src"]}) imports `{v["import"]}` ({v["tgt"]}) [VIOLATION]')
(out / "audit-report.md").write_text("\n".join(lines), encoding="utf-8")

(out / "violations.json").write_text(
    json.dumps({"violations": violations, "long_functions": long_funcs, "missing_types": missing_types}, indent=2),
    encoding="utf-8",
)

counts = {"Violations": len(violations), "Long Functions": len(long_funcs), "Missing Types": len(missing_types)}
html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Services Audit</title>
<script src="https://d3js.org/d3.v7.min.js"></script><style>body{{font-family:system-ui;max-width:900px;margin:2em auto}}
.bar{{fill:#6366f1}}.bar:hover{{fill:#4f46e5}}.label{{font-size:12px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:6px;text-align:left}}th{{background:#f5f5f5}}</style></head><body>
<h1>Services Audit — D3.js Summary</h1>
<div id="chart"></div>
<h2>Top 20 Violations</h2><table><tr><th>File</th><th>Source Layer</th><th>Imported</th><th>Target Layer</th></tr>
"""
for v in sorted(violations, key=lambda x: x["file"])[:20]:
    html += f"<tr><td>{v['file']}</td><td>{v['src']}</td><td>{v['import']}</td><td>{v['tgt']}</td></tr>"
html += f"</table><p>Total: {len(violations)} violations | {len(long_funcs)} long functions | {len(missing_types)} missing types</p>"
html += "<script>const data=["
for k, v in counts.items():
    html += f'{{name:"{k}",count:{v}}},'
html += "];const w=600,h=300,m={top:20,right:20,bottom:50,left:120};"
html += 'const svg=d3.select("#chart").append("svg").attr("width",w).attr("height",h);'
html += "const x=d3.scaleLinear().domain([0,d3.max(data,d=>d.count)]).range([m.left,w-m.right]);"
html += "const y=d3.scaleBand().domain(data.map(d=>d.name)).range([m.top,h-m.bottom]).padding(0.3);"
html += 'svg.append("g").call(d3.axisLeft(y));svg.append("g").attr("transform",`translate(0,${h-m.bottom})`).call(d3.axisBottom(x).ticks(5));'
html += 'svg.selectAll(".bar").data(data).join("rect").attr("class","bar").attr("y",d=>y(d.name)).attr("x",m.left).attr("width",d=>x(d.count)-m.left).attr("height",y.bandwidth());'
html += 'svg.selectAll(".label").data(data).join("text").attr("class","label").attr("y",d=>y(d.name)+y.bandwidth()/2).attr("x",d=>x(d.count)+5).attr("dy","0.35em").text(d=>d.count);'
html += "</script></body></html>"
(out / "summary.html").write_text(html, encoding="utf-8")

print(f"Done. {len(lines)} lines, {len(violations)} violations, {len(long_funcs)} long funcs, {len(missing_types)} missing types.")
