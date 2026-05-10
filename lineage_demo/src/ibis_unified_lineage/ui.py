from __future__ import annotations

import html
import json
from pathlib import Path

from ibis_unified_lineage.models import LineageGraph


def write_lineage_ui(graph: LineageGraph, path: str | Path, *, title: str = "Ibis Unified Column Lineage") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(graph.to_dict(), indent=2)
    path.write_text(_html(title=title, payload=payload), encoding="utf-8")
    return path


def _html(*, title: str, payload: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --ink: #19212a;
      --muted: #637083;
      --panel: #ffffff;
      --line: #d8dee9;
      --value: #2166ac;
      --filter: #b2182b;
      --join: #5aae61;
      --group: #7b3294;
      --order: #d6604d;
      --opaque: #4d4d4d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.4 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 24px 28px 16px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      font-weight: 720;
      letter-spacing: 0;
    }}
    .summary {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
    }}
    .summary span, .badge {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 10px;
      background: #fbfcfe;
    }}
    main {{
      padding: 22px 28px 32px;
      display: grid;
      grid-template-columns: 320px minmax(420px, 1fr) 320px;
      gap: 18px;
      min-width: 980px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .panel h2 {{
      margin: 0;
      padding: 12px 14px;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
    }}
    .dataset {{
      padding: 12px 14px 14px;
      border-bottom: 1px solid var(--line);
    }}
    .dataset:last-child {{ border-bottom: 0; }}
    .dataset-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
      font-weight: 700;
    }}
    .engine {{
      color: var(--muted);
      font-size: 11px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      white-space: nowrap;
    }}
    .column {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      margin: 4px 0;
      padding: 5px 7px;
      border-radius: 6px;
      background: #f9fafc;
      border: 1px solid transparent;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    .column[data-active="true"] {{
      background: #eef5ff;
      border-color: #b9d6fb;
    }}
    .dtype {{ color: var(--muted); }}
    .canvas {{
      position: relative;
      min-height: 760px;
      background: linear-gradient(#ffffff, #fbfcfe);
    }}
    #edges {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }}
    .edge-label {{
      position: absolute;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.92);
      font-size: 11px;
      color: var(--muted);
      transform: translate(-50%, -50%);
      white-space: nowrap;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }}
    .legend span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--value);
    }}
    pre {{
      margin: 0;
      max-height: 280px;
      overflow: auto;
      padding: 12px 14px;
      color: #2a3440;
      background: #fbfcfe;
      border-top: 1px solid var(--line);
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>{safe_title}</h1>
    <div class="summary" id="summary"></div>
  </header>
  <main>
    <section class="panel" id="sources"><h2>Source Columns</h2></section>
    <section class="panel canvas">
      <h2>Column-Level Lineage Edges</h2>
      <div class="legend" id="legend"></div>
      <svg id="edges" aria-label="lineage edges"></svg>
    </section>
    <section class="panel" id="targets"><h2>Output Columns</h2></section>
  </main>
  <section class="panel" style="margin: 0 28px 28px;">
    <h2>Raw Lineage JSON</h2>
    <pre id="json"></pre>
  </section>
  <script type="application/json" id="lineage-data">{payload}</script>
  <script>
    const graph = JSON.parse(document.getElementById("lineage-data").textContent);
    const byDataset = graph.datasets;
    const roles = {{
      value: "var(--value)",
      filter: "var(--filter)",
      join: "var(--join)",
      group: "var(--group)",
      order: "var(--order)",
      opaque: "var(--opaque)",
      unknown: "var(--opaque)"
    }};

    function columnId(ref) {{
      return `${{ref.dataset}}.${{ref.column}}`.replace(/[^A-Za-z0-9_-]/g, "_");
    }}

    function columnsForDataset(datasetKey, edges, side) {{
      const names = new Set();
      for (const edge of edges) {{
        const ref = side === "source" ? edge.source : edge.target;
        if (ref.dataset === datasetKey) names.add(ref.column);
      }}
      return [...names].sort();
    }}

    function renderDataset(parent, datasetKey, side) {{
      const dataset = byDataset[datasetKey];
      const columns = side === "target"
        ? graph.outputs.filter(ref => ref.dataset === datasetKey).map(ref => ref.column)
        : columnsForDataset(datasetKey, graph.edges, "source");
      if (!columns.length) return;
      const root = document.createElement("div");
      root.className = "dataset";
      const title = document.createElement("div");
      title.className = "dataset-title";
      title.innerHTML = `<span>${{dataset.logical_name || dataset.qualified_name || dataset.name}}</span><span class="engine">${{dataset.engine}}</span>`;
      root.appendChild(title);
      const schema = new Map((dataset.schema || []).map(col => [col.name, col.dtype]));
      for (const column of columns) {{
        const row = document.createElement("div");
        row.className = "column";
        row.id = `${{side}}-${{columnId({{ dataset: datasetKey, column }})}}`;
        row.dataset.active = "true";
        row.innerHTML = `<span>${{column}}</span><span class="dtype">${{schema.get(column) || ""}}</span>`;
        root.appendChild(row);
      }}
      parent.appendChild(root);
    }}

    function render() {{
      const sourcePanel = document.getElementById("sources");
      const targetPanel = document.getElementById("targets");
      const sourceDatasets = new Set(graph.edges.map(edge => edge.source.dataset));
      const targetDatasets = new Set(graph.outputs.map(output => output.dataset));
      for (const key of [...sourceDatasets].sort()) renderDataset(sourcePanel, key, "source");
      for (const key of [...targetDatasets].sort()) renderDataset(targetPanel, key, "target");

      document.getElementById("summary").innerHTML = [
        `${{Object.keys(graph.datasets).length}} datasets`,
        `${{graph.outputs.length}} output columns`,
        `${{graph.edges.length}} column edges`,
        `job: ${{graph.metadata.job_name || "unknown"}}`
      ].map(text => `<span>${{text}}</span>`).join("");

      document.getElementById("legend").innerHTML = Object.entries(roles)
        .filter(([role]) => graph.edges.some(edge => edge.role === role))
        .map(([role, color]) => `<span><i class="dot" style="background:${{color}}"></i>${{role}}</span>`)
        .join("");

      document.getElementById("json").textContent = JSON.stringify(graph, null, 2);
      requestAnimationFrame(drawEdges);
    }}

    function drawEdges() {{
      const svg = document.getElementById("edges");
      const canvas = svg.parentElement.getBoundingClientRect();
      svg.setAttribute("viewBox", `0 0 ${{canvas.width}} ${{canvas.height}}`);
      svg.innerHTML = "";
      document.querySelectorAll(".edge-label").forEach(label => label.remove());

      graph.edges.forEach((edge, index) => {{
        const source = document.getElementById(`source-${{columnId(edge.source)}}`);
        const target = document.getElementById(`target-${{columnId(edge.target)}}`);
        if (!source || !target) return;
        const s = source.getBoundingClientRect();
        const t = target.getBoundingClientRect();
        const x1 = 0;
        const y1 = s.top + s.height / 2 - canvas.top;
        const x2 = canvas.width;
        const y2 = t.top + t.height / 2 - canvas.top;
        const bend = canvas.width / 2 + ((index % 9) - 4) * 10;
        const color = roles[edge.role] || roles.unknown;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `M ${{x1}} ${{y1}} C ${{bend}} ${{y1}}, ${{bend}} ${{y2}}, ${{x2}} ${{y2}}`);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", edge.role === "value" ? "1.8" : "1.1");
        path.setAttribute("stroke-opacity", edge.role === "value" ? "0.72" : "0.34");
        svg.appendChild(path);
      }});

      const samples = graph.edges.filter(edge => edge.role !== "join").slice(0, 18);
      samples.forEach((edge, index) => {{
        const source = document.getElementById(`source-${{columnId(edge.source)}}`);
        const target = document.getElementById(`target-${{columnId(edge.target)}}`);
        if (!source || !target) return;
        const s = source.getBoundingClientRect();
        const t = target.getBoundingClientRect();
        const label = document.createElement("div");
        label.className = "edge-label";
        label.textContent = edge.role;
        label.style.left = `${{50 + ((index % 5) - 2) * 6}}%`;
        label.style.top = `${{(s.top + t.top + s.height) / 2 - canvas.top}}px`;
        label.style.borderColor = roles[edge.role] || roles.unknown;
        svg.parentElement.appendChild(label);
      }});
    }}

    window.addEventListener("resize", drawEdges);
    render();
  </script>
</body>
</html>
"""
