#!/usr/bin/env python3
#
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6.0.3",
# ]
# ///

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Ossie Ontology Visualizer

Renders an Ossie ontology document (see ontology/ontology.md) as a diagram:

* ``html`` (default) - a self-contained, interactive HTML page built from
  template.html. It has no external dependencies or network requests; open it
  in any browser.
* ``dot``            - a Graphviz digraph (render with ``dot -Tsvg``)

Entity types are nodes and relationships between entity types are edges
labelled with the relationship name and multiplicity. Relationships to value
types are shown as attributes of their entity type unless ``--value-types
nodes`` is given, in which case value types (and the built-in concepts they
extend) become nodes too. The HTML viewer can also toggle this interactively.

Node positions arranged in the viewer are kept in the browser automatically and
can be exported with "Save layout"; pass that file back with ``--layout`` to
bake the arrangement into the generated page.

Usage:
    python ontology/visualize/visualize.py examples/flights.ontology.yaml --open
    python ontology/visualize/visualize.py examples/flights.ontology.yaml -o flights.html
    python ontology/visualize/visualize.py examples/flights.ontology.yaml --layout flights.layout.json
    python ontology/visualize/visualize.py examples/flights.ontology.yaml -f dot | dot -Tsvg > flights.svg
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install pyyaml")
    sys.exit(1)


ENTITY_TYPE = "EntityType"
VALUE_TYPE = "ValueType"
UNKNOWN_TYPE = "Unknown"

# Built-in concepts from ontology/ontology.md ("Built-in concepts").
BUILTIN_CONCEPTS: dict[str, str] = {
    "Any": ENTITY_TYPE,
    "Boolean": VALUE_TYPE,
    "Date": VALUE_TYPE,
    "DateTime": VALUE_TYPE,
    "Decimal": VALUE_TYPE,
    "Float": VALUE_TYPE,
    "Integer": VALUE_TYPE,
    "String": VALUE_TYPE,
}

FORMATS = ("html", "dot")
VALUE_TYPE_MODES = ("inline", "nodes")

_EXTENSION_FORMATS = {
    ".dot": "dot",
    ".gv": "dot",
    ".html": "html",
    ".htm": "html",
}

TEMPLATE_PATH = Path(__file__).with_name("template.html")


class OntologyError(ValueError):
    """Raised when a document cannot be interpreted as an ontology."""


class LayoutError(ValueError):
    """Raised when a saved layout file cannot be read."""


@dataclass
class Role:
    concept: str
    name: str | None = None


@dataclass
class Relationship:
    owner: str
    name: str
    roles: list[Role]
    multiplicity: str | None = None
    description: str | None = None
    verbalizes: list[str] = field(default_factory=list)
    derived_by: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    iri: str | None = None
    identifying: bool = False

    @property
    def derived(self) -> bool:
        return bool(self.derived_by)


@dataclass
class Concept:
    name: str
    type: str
    description: str | None = None
    extends: list[str] = field(default_factory=list)
    identify_by: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    derived_by: list[str] = field(default_factory=list)
    iri: str | None = None
    relationships: list[Relationship] = field(default_factory=list)
    builtin: bool = False
    declared: bool = True

    @property
    def is_entity(self) -> bool:
        return self.type == ENTITY_TYPE


@dataclass
class Ontology:
    name: str
    description: str | None
    requires: list[str]
    concepts: dict[str, Concept]

    def entity_types(self) -> list[Concept]:
        return [c for c in self.concepts.values() if c.is_entity]

    def relationships(self) -> list[Relationship]:
        return [r for c in self.concepts.values() for r in c.relationships]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_str_list(value: Any) -> list[str]:
    return [str(v) for v in _as_list(value)]


def parse_ontology(doc: Any) -> Ontology:
    """Build an :class:`Ontology` from a parsed ontology document."""
    if not isinstance(doc, dict) or not isinstance(doc.get("ontology"), list):
        raise OntologyError("document has no 'ontology' list; is this an Ossie ontology?")

    concepts: dict[str, Concept] = {}
    for component in doc["ontology"]:
        if not isinstance(component, dict) or "concept" not in component:
            raise OntologyError(f"ontology component without a 'concept' name: {component!r}")
        name = str(component["concept"])
        if name in concepts:
            raise OntologyError(f"concept '{name}' is declared more than once")
        identify_by = _as_str_list(component.get("identify_by"))
        concept = Concept(
            name=name,
            type=str(component.get("type", UNKNOWN_TYPE)),
            description=component.get("description"),
            extends=_as_str_list(component.get("extends")),
            identify_by=identify_by,
            requires=_as_str_list(component.get("requires")),
            derived_by=_as_str_list(component.get("derived_by")),
            iri=component.get("iri"),
            builtin=False,
        )
        for rel in _as_list(component.get("relationships")):
            if not isinstance(rel, dict) or "name" not in rel:
                raise OntologyError(f"relationship without a 'name' on concept '{name}': {rel!r}")
            roles = [
                Role(concept=str(r["concept"]), name=r.get("name"))
                for r in _as_list(rel.get("roles"))
                if isinstance(r, dict) and "concept" in r
            ]
            concept.relationships.append(
                Relationship(
                    owner=name,
                    name=str(rel["name"]),
                    roles=roles,
                    multiplicity=rel.get("multiplicity"),
                    description=rel.get("description"),
                    verbalizes=_as_str_list(rel.get("verbalizes")),
                    derived_by=_as_str_list(rel.get("derived_by")),
                    requires=_as_str_list(rel.get("requires")),
                    iri=rel.get("iri"),
                    identifying=str(rel["name"]) in identify_by,
                )
            )
        concepts[name] = concept

    # Add built-in or undeclared concepts that are referenced, so every edge has two ends.
    referenced: list[str] = []
    for concept in list(concepts.values()):
        referenced.extend(concept.extends)
        for rel in concept.relationships:
            referenced.extend(role.concept for role in rel.roles)
    for ref in referenced:
        if ref in concepts:
            continue
        if ref in BUILTIN_CONCEPTS:
            concepts[ref] = Concept(name=ref, type=BUILTIN_CONCEPTS[ref], builtin=True)
        else:
            concepts[ref] = Concept(name=ref, type=UNKNOWN_TYPE, declared=False)

    return Ontology(
        name=str(doc.get("name", "Ontology")),
        description=doc.get("description"),
        requires=_as_str_list(doc.get("requires")),
        concepts=concepts,
    )


def load_ontology(path: Path) -> Ontology:
    """Load an ontology from a YAML or JSON file."""
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return parse_ontology(doc)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _is_node(concept: Concept, value_types: str) -> bool:
    """Whether a concept is drawn as its own node in the given value-type mode."""
    return concept.is_entity or value_types == "nodes"


def _multiplicity_ends(rel: Relationship) -> tuple[str, str] | None:
    """UML-style (source, target) multiplicities for a binary relationship."""
    if len(rel.roles) != 1:
        return None
    if rel.multiplicity == "ManyToOne":
        return "*", "0..1"
    if rel.multiplicity == "OneToOne":
        return "0..1", "0..1"
    return None


def _attribute_text(rel: Relationship) -> str:
    prefix = "/" if rel.derived else ""
    if not rel.roles:
        return f"{prefix}{rel.name} : unary"
    return f"{prefix}{rel.name} : " + " × ".join(role.concept for role in rel.roles)


def _edge_label(rel: Relationship) -> str:
    label = ("/" if rel.derived else "") + rel.name
    if rel.identifying:
        label += " (id)"
    return label


def _split_relationship(ontology: Ontology, rel: Relationship, value_types: str) -> tuple[list[str], bool]:
    """Return (edge targets, show-as-attribute) for a relationship."""
    targets = [
        role.concept for role in rel.roles if _is_node(ontology.concepts[role.concept], value_types)
    ]
    # Attributes keep relationships visible whose roles are not all drawn as edges
    # (value-type roles in inline mode, unary relationships, and n-ary relationships).
    as_attribute = len(rel.roles) != 1 or not targets
    return targets, as_attribute


def _visible_concepts(ontology: Ontology, value_types: str) -> list[Concept]:
    return [c for c in ontology.concepts.values() if _is_node(c, value_types)]


# ---------------------------------------------------------------------------
# Graphviz DOT
# ---------------------------------------------------------------------------


def _dot_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dot_colors(concept: Concept) -> tuple[str, str]:
    if concept.builtin:
        return "#eceff1", "#90a4ae"
    if not concept.declared:
        return "#ffebee", "#e53935"
    if concept.type == VALUE_TYPE:
        return "#e8f5e9", "#43a047"
    return "#e3f2fd", "#1e88e5"


def to_dot(ontology: Ontology, value_types: str = "inline") -> str:
    """Render the ontology as a Graphviz digraph."""
    visible = _visible_concepts(ontology, value_types)
    lines = [
        f"digraph {_dot_quote(ontology.name)} {{",
        "  graph [rankdir=LR, fontname=Helvetica, nodesep=0.4, ranksep=0.9];",
        "  node [shape=plain, fontname=Helvetica, fontsize=11];",
        "  edge [fontname=Helvetica, fontsize=9, color=\"#546e7a\"];",
    ]
    edges: list[str] = []
    for concept in visible:
        fill, stroke = _dot_colors(concept)
        rows = [f'<tr><td bgcolor="{stroke}"><font color="white"><b>{html.escape(concept.name)}</b></font></td></tr>']
        stereotype = (
            "built-in" if concept.builtin
            else "undeclared" if not concept.declared
            else "value type" if concept.type == VALUE_TYPE
            else None
        )
        if stereotype:
            rows.append(f'<tr><td><font point-size="9">«{stereotype}»</font></td></tr>')
        for rel in concept.relationships:
            targets, as_attribute = _split_relationship(ontology, rel, value_types)
            if as_attribute:
                text = html.escape(_attribute_text(rel))
                if rel.identifying:
                    text = f"<u>{text}</u>"
                if rel.derived:
                    text = f"<i>{text}</i>"
                rows.append(f'<tr><td align="left">{text}</td></tr>')
            ends = _multiplicity_ends(rel)
            for target in targets:
                attrs = [f"label={_dot_quote(_edge_label(rel))}"]
                if ends:
                    attrs += [f"taillabel={_dot_quote(ends[0])}", f"headlabel={_dot_quote(ends[1])}"]
                if rel.derived:
                    attrs.append("style=dashed")
                edges.append(f"  {_dot_quote(concept.name)} -> {_dot_quote(target)} [{', '.join(attrs)}];")
        for parent in concept.extends:
            if _is_node(ontology.concepts[parent], value_types):
                edges.append(
                    f"  {_dot_quote(concept.name)} -> {_dot_quote(parent)} [arrowhead=empty, color=\"#8e24aa\"];"
                )
        table = (
            f'<table border="1" cellborder="0" cellspacing="0" cellpadding="4" '
            f'bgcolor="{fill}" color="{stroke}">{"".join(rows)}</table>'
        )
        lines.append(f"  {_dot_quote(concept.name)} [label=<{table}>];")
    lines.extend(edges)
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Interactive HTML
# ---------------------------------------------------------------------------


def to_json_model(ontology: Ontology) -> dict:
    """Serializable view of the ontology consumed by the HTML viewer."""
    return {
        "name": ontology.name,
        "description": ontology.description,
        "requires": ontology.requires,
        "concepts": [
            {
                "name": c.name,
                "type": c.type,
                "builtin": c.builtin,
                "declared": c.declared,
                "description": c.description,
                "extends": c.extends,
                "identify_by": c.identify_by,
                "requires": c.requires,
                "derived_by": c.derived_by,
                "iri": c.iri,
                "relationships": [
                    {
                        "name": r.name,
                        "roles": [{"concept": role.concept, "name": role.name} for role in r.roles],
                        "multiplicity": r.multiplicity,
                        "description": r.description,
                        "verbalizes": r.verbalizes,
                        "derived_by": r.derived_by,
                        "requires": r.requires,
                        "iri": r.iri,
                        "identifying": r.identifying,
                    }
                    for r in c.relationships
                ],
            }
            for c in ontology.concepts.values()
        ],
    }


def _script_json(value: Any) -> str:
    # Escaping "<" prevents "</script>" (or "<!--") inside ontology text from ending the script element.
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def load_layout(path: Path) -> dict:
    """Load node positions saved from the HTML viewer ("Save layout")."""
    with open(path, encoding="utf-8") as f:
        try:
            doc = json.load(f)
        except json.JSONDecodeError as e:
            raise LayoutError(f"not valid JSON: {e}") from e
    nodes = doc.get("nodes") if isinstance(doc, dict) else None
    if not isinstance(nodes, dict):
        raise LayoutError("expected a JSON object with a 'nodes' object of concept positions")
    positions: dict[str, dict] = {}
    for name, pos in nodes.items():
        if not (
            isinstance(pos, dict)
            and all(
                isinstance(pos.get(k), (int, float)) and not isinstance(pos.get(k), bool) and math.isfinite(pos[k])
                for k in ("x", "y")
            )
        ):
            raise LayoutError(f"position of '{name}' needs numeric 'x' and 'y'")
        positions[str(name)] = {"x": pos["x"], "y": pos["y"], "pinned": bool(pos.get("pinned", True))}
    return {"ontology": doc.get("ontology"), "saved_at": doc.get("saved_at"), "nodes": positions}


def to_html(
    ontology: Ontology, value_types: str = "inline", layout: dict | None = None, source: str | None = None
) -> str:
    """Render the ontology as a self-contained interactive HTML page.

    ``layout`` (see :func:`load_layout`) fixes the initial node positions and ``source`` names the
    file the ontology was read from.
    """
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data = {**to_json_model(ontology), "source": source}
    return (
        template.replace("__TITLE__", html.escape(ontology.name))
        .replace("__SHOW_VALUE_TYPES__", "true" if value_types == "nodes" else "false")
        .replace("__LAYOUT__", _script_json(layout))
        .replace("__DATA__", _script_json(data))
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def render(
    ontology: Ontology,
    fmt: str,
    value_types: str = "inline",
    layout: dict | None = None,
    source: str | None = None,
) -> str:
    if fmt == "html":
        return to_html(ontology, value_types, layout, source)
    if fmt == "dot":
        return to_dot(ontology, value_types)
    raise ValueError(f"unknown format '{fmt}'")


def _default_output(source: Path) -> Path:
    # examples/flights.ontology.yaml -> flights.ontology.html (in the current directory)
    return Path(source.stem + ".html")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render an Ossie ontology as an interactive HTML page or a Graphviz diagram."
    )
    parser.add_argument("ontology", type=Path, help="Ontology YAML/JSON file (e.g. examples/flights.ontology.yaml)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file. Use '-' for stdout. Default: <ontology file name>.html for html, stdout for dot",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=FORMATS,
        help="Output format (default: inferred from --output extension, otherwise html)",
    )
    parser.add_argument(
        "--value-types",
        choices=VALUE_TYPE_MODES,
        default="inline",
        help="'inline' lists value-typed relationships as attributes of their entity type; "
        "'nodes' draws value types and their 'extends' hierarchy as nodes (default: inline)",
    )
    parser.add_argument(
        "--layout",
        type=Path,
        help="Layout JSON saved from the HTML viewer ('Save layout'); fixes the initial node positions",
    )
    parser.add_argument("--open", action="store_true", help="Open the generated HTML page in a web browser")
    args = parser.parse_args(argv)

    to_stdout = args.output is not None and str(args.output) == "-"
    fmt = args.format
    if fmt is None:
        fmt = "html" if args.output is None or to_stdout else _EXTENSION_FORMATS.get(args.output.suffix.lower(), "html")
    output_path = None if to_stdout else args.output
    if output_path is None and fmt == "html" and not to_stdout:
        output_path = _default_output(args.ontology)

    try:
        ontology = load_ontology(args.ontology)
    except (OSError, yaml.YAMLError, OntologyError) as e:
        print(f"Error: {args.ontology}: {e}", file=sys.stderr)
        return 1

    layout = None
    if args.layout:
        try:
            layout = load_layout(args.layout)
        except (OSError, LayoutError) as e:
            print(f"Error: {args.layout}: {e}", file=sys.stderr)
            return 1
        unknown = sorted(set(layout["nodes"]) - set(ontology.concepts))
        if unknown:
            print(f"Warning: {args.layout}: ignoring unknown concepts: {', '.join(unknown)}", file=sys.stderr)

    output = render(ontology, fmt, args.value_types, layout, source=args.ontology.name)
    if output_path is None:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(output)
        return 0

    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote {fmt} diagram of '{ontology.name}' to {output_path}", file=sys.stderr)
    if args.open and fmt == "html":
        webbrowser.open(output_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
