---
name: diagram
description: Create architecture and flow diagrams. Generates clean, presentation-ready diagrams using the Python `diagrams` library (cloud/service architecture), Mermaid (flowcharts, sequences, ER), or draw.io XML. Picks the best format for the use case automatically.
allowed-tools: Bash, Glob, Grep, Read, Write, Edit
---

# Diagram Skill

You are an expert at creating clear, beautiful architecture and flow diagrams.

## Input

What to diagram: `$ARGUMENTS`

If no arguments provided, look at the current working directory and ask what they want to visualize.

---

## Format selection — pick automatically

| Use case | Best format |
|---|---|
| Presentation / video / slides | **Excalidraw JSON** → open at excalidraw.com, looks great on screen |
| Cloud/service architecture with icons | **Python `diagrams` library** → renders to PNG |
| Flowchart, sequence, ER, state machine | **Mermaid** → embed in `.md` file |
| Complex layout needing manual editing | **draw.io XML** → save as `.drawio` |

**Default to Excalidraw** when the diagram is for a video, presentation, or needs to look polished.
Default to **Python `diagrams`** for architecture diagrams that need cloud provider icons.
Default to **Mermaid** for flowcharts and sequences embedded in docs.

---

## Excalidraw approach (preferred for presentations/video)

Excalidraw files are plain JSON with a `.excalidraw` extension. Open at excalidraw.com → Import → select the file.

### How to generate
1. Write the JSON to `docs/architecture.excalidraw`
2. Tell the user to open it at excalidraw.com or in the Excalidraw VS Code extension

### JSON structure
```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "https://excalidraw.com",
  "elements": [ ...elements... ],
  "appState": {
    "viewBackgroundColor": "#0f1117",
    "gridSize": null
  },
  "files": {}
}
```

### Element types
- **Rectangle:** `{ "type": "rectangle", "id": "...", "x": 0, "y": 0, "width": 200, "height": 60, "backgroundColor": "#1e3a5f", "strokeColor": "#3b82f6", "fillStyle": "solid", "roughness": 0, "roundness": {"type": 3}, "label": {"text": "payment-service"} }`
- **Arrow:** `{ "type": "arrow", "id": "...", "x": 0, "y": 0, "width": 100, "height": 0, "points": [[0,0],[100,0]], "startBinding": {"elementId": "...", "gap": 5, "focus": 0}, "endBinding": {"elementId": "...", "gap": 5, "focus": 0}, "strokeColor": "#3b82f6" }`
- **Text:** `{ "type": "text", "id": "...", "x": 0, "y": 0, "text": "label", "fontSize": 16, "fontFamily": 1, "textAlign": "center", "strokeColor": "#ffffff" }`
- **Diamond:** `{ "type": "diamond", ... }` — same fields as rectangle

### Style rules for dark presentation diagrams
- Background: `"viewBackgroundColor": "#0f1117"`
- `"roughness": 0` for clean lines (not hand-drawn)
- `"fillStyle": "solid"` for solid fills
- `"roundness": {"type": 3}` for rounded corners on rectangles
- Font sizes: section labels 18-20px, node labels 13-14px, edge labels 11px
- Arrow style: `"strokeStyle": "solid"` or `"dashed": true` for dashed edges
- Group related nodes visually with a large low-opacity background rectangle

### Layout approach
- Plan coordinates on paper first: place sections top-to-bottom, 120-150px vertical gap between rows
- Nodes within a section: 220-260px wide, 50-60px tall, 40px horizontal gap
- Use absolute x/y — no auto-layout

---

## Python `diagrams` library approach

### Setup
```bash
pip install diagrams
# also requires graphviz: apt install graphviz  OR  brew install graphviz
```

### How to generate
1. Write the Python script to a temp file (e.g. `docs/gen_diagram.py`)
2. Run it with `python docs/gen_diagram.py`
3. It outputs a PNG — report the output path to the user
4. Optionally delete the generator script if the user just wants the PNG

### Key imports and patterns

```python
from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.queue import Redis
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.network import Nginx
from diagrams.programming.framework import FastAPI
from diagrams.generic.storage import Storage
from diagrams.generic.compute import Rack
from diagrams.saas.analytics import Datadog
from diagrams.custom import Custom  # for custom icons (pass icon_path=)

with Diagram("Title", show=False, filename="docs/architecture", direction="TB",
             graph_attr={"bgcolor": "#0f1117", "fontcolor": "#ffffff", "pad": "0.5"}):
    with Cluster("Stage 1", graph_attr={"bgcolor": "#064e3b", "fontcolor": "#6ee7b7"}):
        node = Redis("Redis Streams")
```

### Style rules for dark/presentation diagrams
- `graph_attr={"bgcolor": "#0f1117"}` for dark background
- `node_attr={"fontcolor": "#ffffff", "style": "filled", "fillcolor": "#1f2937"}` for dark nodes
- Use `Edge(label="text", color="#color", style="dashed")` for labeled/styled connections
- Keep `direction="TB"` (top-to-bottom) for pipeline flows
- Use `Cluster` for logical groupings (replaces swimlanes)

### Fallback: if `diagrams` lib is not available
Generate a **Mermaid** diagram instead and save it inside a `.md` file. Tell the user to render it at mermaid.live or in their IDE preview.

---

## Mermaid approach

Write clean Mermaid inside a fenced block. Rules:
- Use `flowchart TD` for top-down pipelines
- Use `sequenceDiagram` for request/response flows
- Add `classDef` blocks for color theming
- Keep node labels short (2-4 words) — put detail in comments above the block
- Always wrap in a `.md` file so it renders in IDE/GitHub

---

## draw.io XML approach

Only use when the user explicitly asks for `.drawio` or needs manual editing.
Use `swimlane` style containers, match color schemes, set `background` on the graph model.

---

## Output

Always:
1. Create the file(s)
2. Run the generator if it's a Python script — show the output path
3. Tell the user exactly how to view/render it (IDE preview, mermaid.live, open in draw.io, etc.)
4. If it's a PNG, confirm it was created successfully with `ls -lh <path>`