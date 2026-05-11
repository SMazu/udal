from __future__ import annotations

import html
import json
from pathlib import Path

from ibis_unified_lineage.models import LineageGraph


def write_lineage_ui(graph: LineageGraph, path: str | Path, *, title: str = "Ibis Unified Column Lineage") -> Path:
    """Write a standalone HTML lineage viewer.

    Args:
        graph: Lineage graph to render.
        path: Output HTML path.
        title: Page title.

    Returns:
        The written HTML path.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(graph.to_dict(), indent=2).replace("</", "<\\/")
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
      --bg: #f5f7fa;
      --ink: #18212b;
      --muted: #627084;
      --panel: #ffffff;
      --line: #d8dee8;
      --soft: #f9fafc;
      --value: #2166ac;
      --filter: #b2182b;
      --join: #4d9221;
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
      padding: 22px 28px 16px;
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
      gap: 10px;
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
      padding: 22px 28px 30px;
      overflow-x: auto;
    }}
    .graph-shell {{
      position: relative;
      display: grid;
      grid-template-columns: minmax(280px, 1fr) minmax(280px, 1fr) minmax(280px, 1fr);
      gap: 20px;
      align-items: start;
      min-width: 980px;
    }}
    .panel {{
      position: relative;
      z-index: 1;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 2px rgba(24, 33, 43, .04);
    }}
    .panel h2 {{
      margin: 0;
      padding: 12px 14px;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
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
    .dataset-name {{
      overflow-wrap: anywhere;
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
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      margin: 4px 0;
      min-height: 30px;
      padding: 5px 7px;
      border-radius: 6px;
      background: var(--soft);
      border: 1px solid transparent;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    .column span:first-child {{
      overflow-wrap: anywhere;
    }}
    .column[data-active="true"] {{
      background: #eef5ff;
      border-color: #b9d6fb;
    }}
    .dtype {{ color: var(--muted); white-space: nowrap; }}
    .empty {{
      padding: 18px 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    #edges {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      z-index: 0;
      pointer-events: none;
      overflow: visible;
    }}
    .edge-label {{
      position: absolute;
      z-index: 2;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.94);
      font-size: 11px;
      color: var(--muted);
      transform: translate(-50%, -50%);
      white-space: nowrap;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 28px 22px;
      padding: 12px 14px;
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
    .raw {{
      margin: 0 28px 28px;
    }}
    pre {{
      margin: 0;
      max-height: 320px;
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
    <section class="graph-shell" id="graph-shell">
      <svg id="edges" aria-label="lineage edges"></svg>
      <section class="panel" id="sources"><h2>Source Datasets</h2></section>
      <section class="panel" id="intermediates"><h2>Intermediate Datasets</h2></section>
      <section class="panel" id="targets"><h2>Final Outputs</h2></section>
    </section>
  </main>
  <section class="panel legend" id="legend"></section>
  <section class="panel raw">
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

    function columnId(ref, tier) {{
      return `${{tier}}-${{ref.dataset}}.${{ref.column}}`.replace(/[^A-Za-z0-9_-]/g, "_");
    }}

    function datasetLabel(dataset) {{
      return dataset.logical_name || dataset.qualified_name || dataset.name;
    }}

    function sortedColumns(datasetKey, tier) {{
      const names = new Set();
      if (tier === "target" || tier === "intermediate") {{
        graph.outputs
          .filter(ref => ref.dataset === datasetKey)
          .forEach(ref => names.add(ref.column));
      }}
      if (tier === "source" || tier === "intermediate") {{
        graph.edges
          .filter(edge => edge.source.dataset === datasetKey)
          .forEach(edge => names.add(edge.source.column));
      }}
      if (!names.size) {{
        graph.edges
          .filter(edge => edge.target.dataset === datasetKey)
          .forEach(edge => names.add(edge.target.column));
      }}
      return [...names].sort();
    }}

    function renderDataset(parent, datasetKey, tier) {{
      const dataset = byDataset[datasetKey];
      if (!dataset) return;
      const columns = sortedColumns(datasetKey, tier);
      if (!columns.length) return;
      const root = document.createElement("div");
      root.className = "dataset";
      const title = document.createElement("div");
      title.className = "dataset-title";
      title.innerHTML = `<span class="dataset-name">${{datasetLabel(dataset)}}</span><span class="engine">${{dataset.engine}}</span>`;
      root.appendChild(title);
      const schema = new Map((dataset.schema || []).map(col => [col.name, col.dtype]));
      for (const column of columns) {{
        const row = document.createElement("div");
        row.className = "column";
        row.id = columnId({{ dataset: datasetKey, column }}, tier);
        row.dataset.active = "true";
        row.innerHTML = `<span>${{column}}</span><span class="dtype">${{schema.get(column) || ""}}</span>`;
        root.appendChild(row);
      }}
      parent.appendChild(root);
    }}

    function addEmptyState(parent) {{
      if (parent.querySelector(".dataset")) return;
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No materialized datasets in this tier";
      parent.appendChild(empty);
    }}

    function tiers() {{
      const sourceDatasets = new Set(graph.edges.map(edge => edge.source.dataset));
      const outputDatasets = new Set(graph.outputs.map(output => output.dataset));
      const intermediate = [...outputDatasets].filter(key => sourceDatasets.has(key)).sort();
      const final = [...outputDatasets].filter(key => !sourceDatasets.has(key)).sort();
      const sources = [...sourceDatasets].filter(key => !outputDatasets.has(key)).sort();
      return {{ sources, intermediate, final: final.length ? final : [...outputDatasets].sort() }};
    }}

    function render() {{
      const tierSets = tiers();
      for (const key of tierSets.sources) renderDataset(document.getElementById("sources"), key, "source");
      for (const key of tierSets.intermediate) renderDataset(document.getElementById("intermediates"), key, "intermediate");
      for (const key of tierSets.final) renderDataset(document.getElementById("targets"), key, "target");
      addEmptyState(document.getElementById("intermediates"));

      const stageText = Array.isArray(graph.metadata.stages) ? `stages: ${{graph.metadata.stages.join(" -> ")}}` : `job: ${{graph.metadata.job_name || "unknown"}}`;
      document.getElementById("summary").innerHTML = [
        `${{Object.keys(graph.datasets).length}} datasets`,
        `${{graph.outputs.length}} output columns`,
        `${{graph.edges.length}} column edges`,
        stageText
      ].map(text => `<span>${{text}}</span>`).join("");

      document.getElementById("legend").innerHTML = Object.entries(roles)
        .filter(([role]) => graph.edges.some(edge => edge.role === role))
        .map(([role, color]) => `<span><i class="dot" style="background:${{color}}"></i>${{role}}</span>`)
        .join("");

      document.getElementById("json").textContent = JSON.stringify(graph, null, 2);
      requestAnimationFrame(drawEdges);
    }}

    function sourceTier(ref, tierSets) {{
      return tierSets.intermediate.includes(ref.dataset) ? "intermediate" : "source";
    }}

    function targetTier(ref, tierSets) {{
      return tierSets.intermediate.includes(ref.dataset) ? "intermediate" : "target";
    }}

    function drawEdges() {{
      const shell = document.getElementById("graph-shell");
      const svg = document.getElementById("edges");
      const shellBox = shell.getBoundingClientRect();
      svg.setAttribute("viewBox", `0 0 ${{shellBox.width}} ${{shellBox.height}}`);
      svg.innerHTML = "";

      const tierSets = tiers();
      graph.edges.forEach((edge, index) => {{
        const source = document.getElementById(columnId(edge.source, sourceTier(edge.source, tierSets)));
        const target = document.getElementById(columnId(edge.target, targetTier(edge.target, tierSets)));
        if (!source || !target) return;
        const s = source.getBoundingClientRect();
        const t = target.getBoundingClientRect();
        const x1 = s.right - shellBox.left;
        const y1 = s.top + s.height / 2 - shellBox.top;
        const x2 = t.left - shellBox.left;
        const y2 = t.top + t.height / 2 - shellBox.top;
        const bend = Math.max(40, Math.abs(x2 - x1) / 2) + ((index % 7) - 3) * 7;
        const color = roles[edge.role] || roles.unknown;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `M ${{x1}} ${{y1}} C ${{x1 + bend}} ${{y1}}, ${{x2 - bend}} ${{y2}}, ${{x2}} ${{y2}}`);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", edge.role === "value" ? "1.8" : "1.1");
        path.setAttribute("stroke-opacity", edge.role === "value" ? "0.72" : "0.34");
        svg.appendChild(path);
      }});
    }}

    window.addEventListener("resize", drawEdges);
    render();
  </script>
</body>
</html>
"""
