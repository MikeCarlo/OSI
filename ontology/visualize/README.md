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

# Ontology viewer

[`ontology-viewer.html`](ontology-viewer.html) shows an [Ossie ontology](../ontology.md) as an
interactive diagram. It is a single, self-contained HTML file: there is nothing to install,
build or run, and it works offline.

## Usage

1. Open `ontology-viewer.html` in a browser, for example by double-clicking it. You can also copy
   the file anywhere or send it to someone; it doesn't need the rest of the repository.
2. Click **Open ontology…** and pick an ontology `.yaml` or `.json` file, such as
   [`examples/flights.ontology.yaml`](../../examples/flights.ontology.yaml). You can also drop the
   file onto the page.

Files are read by the page on your computer and never uploaded.

**Live updates (Edge, Chrome):**
- The page keeps watching the file you opened. It redraws within about a second every time you
  save it, keeping your node positions. A green **live** label next to the file name shows that it
  is watching.
- If you save the file while it is broken (for example half-typed YAML), the error appears in red
  with its line number. The last good version stays on screen until you fix it.

**Other browsers** (Firefox, Safari) read the file once. Open it again to see later changes.

**Coming back later:**
- The page reopens the last ontology you opened.
- In Edge and Chrome, click **Resume live updates** to keep watching the file; the browser asks
  for permission again after the page is closed.
- Click **✕** next to the file name to close the ontology.

## Reading the diagram

- Entity types are blue boxes. Relationships between entity types are arrows labelled with the
  relationship name and multiplicity (`*` → `0..1` for `ManyToOne`). 🔑 marks identifying
  relationships and dashed arrows are derived relationships.
- Click a concept to see its description, `extends` hierarchy, identifiers, constraints,
  relationships with their verbalizations, and the relationships that reference it.
- **Value types** draws value types (green) and their `extends` chains (purple arrows) as nodes.
  With value types on, **Built-ins** adds the built-in concepts they end in, such as `String` and
  `Integer` (gray).
- Search with the box at the top, drag the background to pan, and scroll to zoom. Hover an arrow
  to read its verbalization.

## Arranging the diagram

Drag a node to pin it where you want it; double-click it to unpin it. Your arrangement is saved in
the browser (per ontology name) every time you move a node, and comes back the next time you open
that ontology.

The **Layout** menu has:
- **Save layout**, which downloads the positions as `<ontology>.layout.json` so you can share them.
- **Load layout…**, which applies such a file. Dropping a `.layout.json` file on the page does the
  same.
- **Reset layout**, which discards the arrangement and lays the diagram out again.

## Supported YAML

The page reads YAML itself, without libraries. It supports what Ossie documents use:
- nested mappings and lists;
- `[...]` and `{...}` collections, also across several lines;
- quoted and unquoted text, and `|` and `>` text blocks;
- comments.

Anchors (`&`/`*`), tags (`!`) and multiple documents in one file are reported as errors.

## Tests

```bash
uv run --with pytest --with pyyaml -m pytest ontology/visualize/tests
```

The tests run the page in headless Chrome, Edge or Chromium. They check:
- the YAML reader against PyYAML, using the example files and edge cases;
- how the page interprets ontology documents;
- the user interface, including opening, live updates, closing, the Layout menu and toggles.

They are skipped when no browser is found. Set `OSSIE_TEST_BROWSER` to the browser executable to
choose one.
