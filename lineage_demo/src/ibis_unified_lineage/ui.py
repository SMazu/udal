from __future__ import annotations

import html
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from ibis_unified_lineage.models import ColumnRef, LineageGraph
from ibis_unified_lineage.pipeline import transitive_dependency_pairs


def write_lineage_ui(graph: LineageGraph, path: str | Path, *, title: str = "Ibis Unified Column Lineage") -> Path:
    """Write a standalone arbitrary-depth DAG lineage viewer.

    Args:
        graph: Lineage graph to render.
        path: Output HTML path.
        title: Page title.

    Returns:
        The written HTML path.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_ui_payload(graph), indent=2).replace("</", "<\\/")
    path.write_text(_html(title=title, payload=payload), encoding="utf-8")
    return path


def _ui_payload(graph: LineageGraph) -> dict[str, Any]:
    payload = graph.to_dict()
    payload["dag"] = _dag_metadata(graph)
    payload["transitive_edges"] = _transitive_edge_records(graph)
    return payload


def _dag_metadata(graph: LineageGraph) -> dict[str, Any]:
    dataset_edges = _dataset_edges(graph)
    layers = _dataset_layers(graph, dataset_edges)
    incoming = {edge["target"] for edge in dataset_edges}
    outgoing = {edge["source"] for edge in dataset_edges}
    output_datasets = {output.dataset for output in graph.outputs}

    return {
        "model": "arbitrary-depth-materialized-dag",
        "layers": layers,
        "dataset_edges": dataset_edges,
        "source_datasets": sorted(key for key in graph.datasets if key not in incoming),
        "final_output_datasets": sorted(key for key in output_datasets if key not in outgoing) or sorted(output_datasets),
        "materialized_datasets": sorted(output_datasets),
        "columns": _columns_by_dataset(graph),
    }


def _dataset_edges(graph: LineageGraph) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in graph.edges:
        if edge.source.dataset == edge.target.dataset:
            continue
        key = (edge.source.dataset, edge.target.dataset)
        record = grouped.setdefault(
            key,
            {
                "source": edge.source.dataset,
                "target": edge.target.dataset,
                "roles": set(),
                "stages": set(),
                "column_edge_count": 0,
            },
        )
        record["roles"].add(edge.role)
        if edge.stage_id:
            record["stages"].add(edge.stage_id)
        record["column_edge_count"] += 1

    return [
        {
            "source": source,
            "target": target,
            "roles": sorted(record["roles"]),
            "stages": sorted(record["stages"]),
            "column_edge_count": record["column_edge_count"],
        }
        for (source, target), record in sorted(grouped.items())
    ]


def _dataset_layers(graph: LineageGraph, dataset_edges: list[dict[str, Any]]) -> list[list[str]]:
    nodes = set(graph.datasets)
    indegree = {node: 0 for node in nodes}
    children: dict[str, set[str]] = {node: set() for node in nodes}
    for edge in dataset_edges:
        source = edge["source"]
        target = edge["target"]
        if source not in nodes or target not in nodes:
            continue
        if target not in children[source]:
            children[source].add(target)
            indegree[target] += 1

    ready = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    ranks = {node: 0 for node in ready}
    visited: list[str] = []
    while ready:
        node = ready.popleft()
        visited.append(node)
        for child in sorted(children[node]):
            ranks[child] = max(ranks.get(child, 0), ranks[node] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(visited) != len(nodes):
        for node in sorted(nodes - set(visited)):
            ranks.setdefault(node, max(ranks.values(), default=0) + 1)

    layers: dict[int, list[str]] = defaultdict(list)
    for node, rank in ranks.items():
        layers[rank].append(node)
    return [sorted(layer) for _, layer in sorted(layers.items())]


def _columns_by_dataset(graph: LineageGraph) -> dict[str, list[dict[str, str]]]:
    columns: dict[str, dict[str, str]] = defaultdict(dict)
    for key, dataset in graph.datasets.items():
        for name, dtype in dataset.schema:
            columns[key][name] = dtype
    for output in graph.outputs:
        columns[output.dataset].setdefault(output.column, "")
    for edge in graph.edges:
        columns[edge.source.dataset].setdefault(edge.source.column, "")
        columns[edge.target.dataset].setdefault(edge.target.column, "")
    return {
        dataset: [
            {"name": name, "dtype": dtype}
            for name, dtype in sorted(values.items())
        ]
        for dataset, values in sorted(columns.items())
    }


def _transitive_edge_records(graph: LineageGraph) -> list[dict[str, Any]]:
    columns = _column_ref_index(graph)
    records = []
    for source, target in sorted(transitive_dependency_pairs(graph)):
        source_ref = columns.get(source)
        target_ref = columns.get(target)
        if source_ref is None or target_ref is None:
            continue
        records.append(
            {
                "source": source_ref.to_dict(),
                "target": target_ref.to_dict(),
                "role": "transitive",
                "transform": "transitive",
                "expression": f"{source} -> {target}",
                "confidence": "derived",
                "stage_id": "transitive",
            }
        )
    return records


def _column_ref_index(graph: LineageGraph) -> dict[str, ColumnRef]:
    index: dict[str, ColumnRef] = {}
    for output in graph.outputs:
        index[_logical_column_key(graph, output)] = output
    for edge in graph.edges:
        index[_logical_column_key(graph, edge.source)] = edge.source
        index[_logical_column_key(graph, edge.target)] = edge.target
    return index


def _logical_column_key(graph: LineageGraph, column: ColumnRef) -> str:
    dataset = graph.datasets.get(column.dataset)
    dataset_name = dataset.logical_name if dataset and dataset.logical_name else column.dataset
    return f"{dataset_name}.{column.column}"


def _html(*, title: str, payload: str) -> str:
    safe_title = html.escape(title)
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --ink: #18212b;
      --muted: #627084;
      --panel: #ffffff;
      --line: #d8dee8;
      --soft: #f9fafc;
      --focus: #eef5ff;
      --value: #2166ac;
      --filter: #b2182b;
      --join: #4d9221;
      --group: #7b3294;
      --order: #d6604d;
      --transitive: #00857a;
      --opaque: #4d4d4d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.4 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      padding: 22px 28px 16px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0 0 8px;
      font-size: 24px;
      font-weight: 720;
      letter-spacing: 0;
    }
    .summary, .controls, .legend {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }
    .summary span, .badge {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 10px;
      background: #fbfcfe;
      color: var(--muted);
    }
    .controls {
      padding: 14px 28px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }
    label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    input, select {
      height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 9px;
      color: var(--ink);
      background: #ffffff;
      font: inherit;
      font-size: 13px;
    }
    input[type="checkbox"] {
      height: auto;
      margin: 0;
    }
    main {
      padding: 22px 28px 30px;
      overflow-x: auto;
    }
    .dag-shell {
      position: relative;
      min-width: 1120px;
    }
    #edges {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      z-index: 0;
      pointer-events: none;
      overflow: visible;
    }
    .layers {
      position: relative;
      z-index: 1;
      display: grid;
      gap: 18px;
      align-items: start;
    }
    .layer {
      min-width: 250px;
    }
    .layer-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin: 0 0 8px;
      padding: 0 2px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .dataset {
      margin-bottom: 12px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 2px rgba(24, 33, 43, .04);
    }
    .dataset[data-hidden="true"] {
      display: none;
    }
    .dataset-title {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 12px 14px 9px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
      font-weight: 700;
    }
    .dataset-name {
      overflow-wrap: anywhere;
    }
    .engine {
      color: var(--muted);
      font-size: 11px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      white-space: nowrap;
      background: #ffffff;
    }
    .flags {
      display: flex;
      gap: 5px;
      padding: 0 14px 8px;
      background: #fbfcfe;
    }
    .flag {
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 11px;
      padding: 2px 7px;
      background: #ffffff;
    }
    .columns {
      padding: 8px 10px 10px;
    }
    .column {
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
    }
    .column[data-hidden="true"] {
      display: none;
    }
    .column[data-active="true"] {
      background: var(--focus);
      border-color: #b9d6fb;
    }
    .column span:first-child {
      overflow-wrap: anywhere;
    }
    .dtype {
      color: var(--muted);
      white-space: nowrap;
    }
    .panel {
      margin: 0 28px 28px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .panel h2 {
      margin: 0;
      padding: 12px 14px;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
    }
    .legend {
      padding: 12px 14px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--value);
    }
    pre {
      margin: 0;
      max-height: 360px;
      overflow: auto;
      padding: 12px 14px;
      color: #2a3440;
      background: #fbfcfe;
      border-top: 1px solid var(--line);
      font-size: 12px;
    }
  </style>
</head>
<body>
  <header>
    <h1>__TITLE__</h1>
    <div class="summary" id="summary"></div>
  </header>
  <section class="controls" aria-label="lineage controls">
    <label>Mode
      <select id="mode">
        <option value="direct">Direct materialized lineage</option>
        <option value="transitive">Transitive raw-to-output lineage</option>
      </select>
    </label>
    <label>Dataset <input id="dataset-filter" placeholder="sales.orders" /></label>
    <label>Column <input id="column-filter" placeholder="total_net" /></label>
    <label>Stage <input id="stage-filter" placeholder="stage id" /></label>
    <label>Engine <input id="engine-filter" placeholder="duckdb" /></label>
    <span id="role-controls" class="controls"></span>
  </section>
  <main>
    <section class="dag-shell" id="dag-shell" data-layout="arbitrary-depth-dag">
      <svg id="edges" aria-label="lineage edges"></svg>
      <section class="layers" id="layers"></section>
    </section>
  </main>
  <section class="panel legend" id="legend"></section>
  <section class="panel">
    <h2>Raw Lineage JSON</h2>
    <pre id="json"></pre>
  </section>
  <script type="application/json" id="lineage-data">__PAYLOAD__</script>
  <script>
    const graph = JSON.parse(document.getElementById("lineage-data").textContent);
    const roles = {
      value: "var(--value)",
      filter: "var(--filter)",
      join: "var(--join)",
      group: "var(--group)",
      order: "var(--order)",
      opaque: "var(--opaque)",
      unknown: "var(--opaque)",
      transitive: "var(--transitive)"
    };
    const filters = {
      dataset: "",
      column: "",
      stage: "",
      engine: "",
      roles: new Set()
    };

    function domId(value) {
      return String(value).replace(/[^A-Za-z0-9_-]/g, "_");
    }

    function columnId(ref) {
      return `col-${domId(ref.dataset)}-${domId(ref.column)}`;
    }

    function datasetLabel(dataset) {
      return dataset.logical_name || dataset.qualified_name || dataset.name;
    }

    function datasetFlags(key) {
      const flags = [];
      if (graph.dag.source_datasets.includes(key)) flags.push("source");
      if (graph.dag.materialized_datasets.includes(key)) flags.push("materialized");
      if (graph.dag.final_output_datasets.includes(key)) flags.push("final");
      return flags;
    }

    function activeEdges() {
      const mode = document.getElementById("mode").value;
      return mode === "transitive" ? graph.transitive_edges : graph.edges;
    }

    function edgeMatches(edge) {
      const sourceDataset = graph.datasets[edge.source.dataset];
      const targetDataset = graph.datasets[edge.target.dataset];
      const datasetText = `${datasetLabel(sourceDataset)} ${datasetLabel(targetDataset)}`.toLowerCase();
      const columnText = `${edge.source.column} ${edge.target.column}`.toLowerCase();
      const stageText = String(edge.stage_id || "").toLowerCase();
      const engineText = `${sourceDataset.engine} ${targetDataset.engine}`.toLowerCase();
      if (filters.dataset && !datasetText.includes(filters.dataset)) return false;
      if (filters.column && !columnText.includes(filters.column)) return false;
      if (filters.stage && !stageText.includes(filters.stage)) return false;
      if (filters.engine && !engineText.includes(filters.engine)) return false;
      return filters.roles.size === 0 || filters.roles.has(edge.role);
    }

    function datasetMatches(key) {
      const dataset = graph.datasets[key];
      const label = datasetLabel(dataset).toLowerCase();
      if (filters.dataset && !label.includes(filters.dataset)) {
        return activeEdges().some(edge => edgeMatches(edge) && (edge.source.dataset === key || edge.target.dataset === key));
      }
      if (filters.engine && !String(dataset.engine).toLowerCase().includes(filters.engine)) return false;
      return true;
    }

    function columnMatches(datasetKey, columnName) {
      if (filters.column && !columnName.toLowerCase().includes(filters.column)) {
        return activeEdges().some(edge => edgeMatches(edge) && (
          (edge.source.dataset === datasetKey && edge.source.column === columnName) ||
          (edge.target.dataset === datasetKey && edge.target.column === columnName)
        ));
      }
      return true;
    }

    function renderControls() {
      const roleValues = [...new Set([...graph.edges, ...graph.transitive_edges].map(edge => edge.role))].sort();
      const root = document.getElementById("role-controls");
      root.innerHTML = roleValues.map(role => (
        `<label><input type="checkbox" value="${role}" checked />${role}</label>`
      )).join("");
      filters.roles = new Set(roleValues);
      root.querySelectorAll("input").forEach(input => {
        input.addEventListener("change", () => {
          filters.roles = new Set([...root.querySelectorAll("input:checked")].map(item => item.value));
          applyFilters();
        });
      });
    }

    function renderGraph() {
      const layers = document.getElementById("layers");
      layers.style.gridTemplateColumns = `repeat(${Math.max(graph.dag.layers.length, 1)}, minmax(250px, 1fr))`;
      layers.innerHTML = "";
      graph.dag.layers.forEach((layer, index) => {
        const layerEl = document.createElement("section");
        layerEl.className = "layer";
        layerEl.innerHTML = `<div class="layer-title"><span>Layer ${index + 1}</span><span>${layer.length} datasets</span></div>`;
        layer.forEach(datasetKey => layerEl.appendChild(renderDataset(datasetKey)));
        layers.appendChild(layerEl);
      });
    }

    function renderDataset(datasetKey) {
      const dataset = graph.datasets[datasetKey];
      const root = document.createElement("article");
      root.className = "dataset";
      root.dataset.datasetKey = datasetKey;
      root.dataset.engine = dataset.engine;
      const flags = datasetFlags(datasetKey).map(flag => `<span class="flag">${flag}</span>`).join("");
      root.innerHTML = `
        <div class="dataset-title">
          <span class="dataset-name">${datasetLabel(dataset)}</span>
          <span class="engine">${dataset.engine}</span>
        </div>
        <div class="flags">${flags}</div>
        <div class="columns"></div>
      `;
      const columns = root.querySelector(".columns");
      (graph.dag.columns[datasetKey] || []).forEach(column => {
        const row = document.createElement("div");
        row.className = "column";
        row.id = columnId({dataset: datasetKey, column: column.name});
        row.dataset.column = column.name;
        row.innerHTML = `<span>${column.name}</span><span class="dtype">${column.dtype || ""}</span>`;
        columns.appendChild(row);
      });
      return root;
    }

    function renderSummary() {
      const stageText = Array.isArray(graph.metadata.stages)
        ? `stages: ${graph.metadata.stages.join(" -> ")}`
        : `job: ${graph.metadata.job_name || "unknown"}`;
      document.getElementById("summary").innerHTML = [
        `${Object.keys(graph.datasets).length} datasets`,
        `${graph.dag.layers.length} layers`,
        `${graph.outputs.length} materialized output columns`,
        `${graph.edges.length} direct column edges`,
        `${graph.transitive_edges.length} transitive edges`,
        stageText
      ].map(text => `<span>${text}</span>`).join("");
    }

    function renderLegend() {
      document.getElementById("legend").innerHTML = Object.entries(roles)
        .filter(([role]) => [...graph.edges, ...graph.transitive_edges].some(edge => edge.role === role))
        .map(([role, color]) => `<span><i class="dot" style="background:${color}"></i>${role}</span>`)
        .join("");
    }

    function bindFilters() {
      document.getElementById("mode").addEventListener("change", applyFilters);
      for (const [id, key] of [
        ["dataset-filter", "dataset"],
        ["column-filter", "column"],
        ["stage-filter", "stage"],
        ["engine-filter", "engine"]
      ]) {
        document.getElementById(id).addEventListener("input", event => {
          filters[key] = event.target.value.trim().toLowerCase();
          applyFilters();
        });
      }
    }

    function applyFilters() {
      document.querySelectorAll(".dataset").forEach(dataset => {
        const key = dataset.dataset.datasetKey;
        dataset.dataset.hidden = String(!datasetMatches(key));
        dataset.querySelectorAll(".column").forEach(column => {
          column.dataset.hidden = String(!columnMatches(key, column.dataset.column));
          column.dataset.active = "false";
        });
      });

      for (const edge of activeEdges().filter(edgeMatches)) {
        const source = document.getElementById(columnId(edge.source));
        const target = document.getElementById(columnId(edge.target));
        if (source) source.dataset.active = "true";
        if (target) target.dataset.active = "true";
      }
      requestAnimationFrame(drawEdges);
    }

    function drawEdges() {
      const shell = document.getElementById("dag-shell");
      const svg = document.getElementById("edges");
      const shellBox = shell.getBoundingClientRect();
      svg.setAttribute("viewBox", `0 0 ${shellBox.width} ${shellBox.height}`);
      svg.innerHTML = "";

      activeEdges().filter(edgeMatches).forEach((edge, index) => {
        const source = document.getElementById(columnId(edge.source));
        const target = document.getElementById(columnId(edge.target));
        if (!source || !target || source.dataset.hidden === "true" || target.dataset.hidden === "true") return;
        const sourceDataset = source.closest(".dataset");
        const targetDataset = target.closest(".dataset");
        if (sourceDataset.dataset.hidden === "true" || targetDataset.dataset.hidden === "true") return;

        const s = source.getBoundingClientRect();
        const t = target.getBoundingClientRect();
        const x1 = s.right - shellBox.left;
        const y1 = s.top + s.height / 2 - shellBox.top;
        const x2 = t.left - shellBox.left;
        const y2 = t.top + t.height / 2 - shellBox.top;
        const bend = Math.max(44, Math.abs(x2 - x1) / 2) + ((index % 9) - 4) * 5;
        const color = roles[edge.role] || roles.unknown;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", edge.role === "transitive" ? "1.2" : "1.8");
        path.setAttribute("stroke-opacity", edge.role === "transitive" ? "0.34" : "0.66");
        svg.appendChild(path);
      });
    }

    renderControls();
    renderGraph();
    renderSummary();
    renderLegend();
    bindFilters();
    document.getElementById("json").textContent = JSON.stringify(graph, null, 2);
    window.addEventListener("resize", drawEdges);
    applyFilters();
  </script>
</body>
</html>
"""
    return template.replace("__TITLE__", safe_title).replace("__PAYLOAD__", payload)
