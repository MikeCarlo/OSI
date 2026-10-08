<!--
  Licensed to the Apache Software Foundation (ASF) under one
  or more contributor license agreements.  See the NOTICE file
  distributed with this work for additional information
  regarding copyright ownership.  The ASF licenses this file
  to you under the Apache License, Version 2.0 (the
  "License"); you may not use this file except in compliance
  with the License.  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing,
  software distributed under the License is distributed on an
  "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
  KIND, either express or implied.  See the License for the
  specific language governing permissions and limitations
  under the License.
-->

# Ontology visualizer

Renders an [Ossie ontology](../ontology.md) as an interactive diagram.

| File | Purpose |
|------|---------|
| [`visualize.py`](visualize.py) | Command-line tool. Reads an ontology YAML/JSON file and writes the diagram |
| [`template.html`](template.html) | The viewer page (HTML, CSS and plain JavaScript) that `visualize.py` fills in. Includes a small YAML reader so the page can open ontology files itself |
| [`tests/`](tests/) | Tests for the tool |

## Usage

```bash
uv run ontology/visualize/visualize.py examples/flights.ontology.yaml --open   # writes flights.ontology.html
uv run ontology/visualize/visualize.py examples/flights.ontology.yaml -o docs/flights.html
```

The output is one self-contained HTML file. It uses no external libraries and makes no network
requests, so you can open it in any browser, offline, or send it to someone. The only Python
dependency is PyYAML.

| Option | Description |
|--------|-------------|
| `-o, --output FILE` | Output file (`-` for stdout). Defaults to `<ontology file name>.html` |
| `-f, --format {html,dot}` | Output format. Inferred from the `--output` extension, otherwise `html` |
| `--value-types {inline,nodes}` | Start with value types listed as attributes (`inline`, default) or drawn as nodes |
| `--layout FILE` | Build node positions saved from the viewer into the page (see [Saving a layout](#saving-a-layout)) |
| `--open` | Open the generated page in a web browser |

## Reading the diagram

- Entity types are blue boxes. Relationships between entity types are arrows labelled with the
  relationship name and multiplicity (`*` → `0..1` for `ManyToOne`). 🔑 marks identifying
  relationships and dashed arrows are derived relationships.
- Click a concept to see its description, `extends` hierarchy, identifiers, constraints,
  relationships with their verbalizations, and the relationships that reference it.
- **Value types** draws value types (green) and their `extends` chains (purple arrows) as nodes.
  **Built-ins** adds built-in concepts like `String`.
- Search with the box at the top, drag the background to pan, and scroll to zoom. Hover an arrow
  to read its verbalization.

## Opening an ontology without regenerating the page

**Open ontology…** loads an ontology `.yaml` or `.json` file straight into any generated page. You
can also drop the file onto the page. You only need to run `visualize.py` once.

- **Live updates (Edge, Chrome):** the page keeps watching the file you opened and redraws within
  about a second each time you save it, keeping your node positions. A green **live** label next
  to the file name shows it is watching. If you save the file while it is broken (for example
  half-typed YAML), the error appears in red with its line number and the last good version stays
  on screen until you fix it.
- **Other browsers** (Firefox, Safari) open the file once. Open it again to see later changes.
- The opened file stays on screen if you refresh the tab. After a refresh, click
  **Resume live updates** to keep watching it, since browsers ask for permission again.
- Click **✕** next to the file name to go back to the ontology built into the page.

The page reads YAML itself, with no libraries. It supports the YAML used by Ossie documents:
nested mappings and lists, `[...]`/`{...}` collections (also across lines), quoted and unquoted
text, `|` and `>` text blocks, and comments. Anchors (`&`/`*`), tags (`!`) and multiple documents
in one file are reported as errors. Generated pages read YAML with PyYAML; the tests check that
both readers agree on the example files and on a set of edge cases.

## Saving a layout

Drag a node to pin it where you want it. Double-click it to unpin it.

- **Automatically:** your arrangement is saved in the browser (`localStorage`, per ontology name)
  every time you move a node. It comes back when you reopen the page, even after regenerating it.
- The **Layout** menu has:
  - **Save layout**, which downloads the positions as `<ontology>.layout.json`.
  - **Load layout…**, which applies such a file. Dropping a `.layout.json` file on the page does
    the same.
  - **Reset layout**, which discards the saved arrangement and returns to the automatic layout,
    or to the layout built into the page.

To share an arrangement, build it into the generated page so everyone who opens it sees the same
layout:

```bash
uv run ontology/visualize/visualize.py examples/flights.ontology.yaml --layout flights.layout.json
```

Concepts missing from the layout file are placed automatically, and concepts in the file that no
longer exist in the ontology are ignored with a warning. If the browser also has a saved
arrangement, the more recently saved one wins.

## Static diagrams with Graphviz

`-f dot` writes a Graphviz digraph instead. Render it with [Graphviz](https://graphviz.org/):

```bash
uv run ontology/visualize/visualize.py examples/flights.ontology.yaml -f dot | dot -Tsvg > flights.svg
```

## Tests

```bash
uv run --with pytest --with pyyaml -m pytest ontology/visualize/tests
```

`tests/test_viewer_js.py` runs the page's JavaScript in headless Chrome, Edge or Chromium. It
compares the YAML reader with PyYAML, and the browser's ontology parsing with `visualize.py`'s,
and exercises the Layout menu, opening files and live updates. It is skipped when no browser is
found; set `OSSIE_TEST_BROWSER` to the browser executable to choose one.
