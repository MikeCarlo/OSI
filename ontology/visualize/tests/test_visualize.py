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

"""Tests for the ontology visualizer (ontology/visualize/visualize.py)."""

import json
import re
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

pytest.importorskip("yaml")

_HERE = Path(__file__).parent
_REPO = _HERE.parents[2]
_SPEC = spec_from_file_location("ossie_visualize", _HERE.parent / "visualize.py")
assert _SPEC is not None and _SPEC.loader is not None
viz = module_from_spec(_SPEC)
# dataclasses resolves annotations through sys.modules, so register before executing.
sys.modules[_SPEC.name] = viz
_SPEC.loader.exec_module(viz)

FLIGHTS = _REPO / "examples" / "flights.ontology.yaml"


@pytest.fixture(scope="module")
def flights():
    return viz.load_ontology(FLIGHTS)


def _embedded_model(page: str) -> dict:
    return _embedded_json(page, "ontology-data")


def _embedded_json(page: str, script_id: str):
    match = re.search(rf'<script id="{script_id}" type="application/json">(.*?)</script>', page, re.DOTALL)
    assert match, f"{script_id} script not found"
    return json.loads(match.group(1))


def test_parses_flights_ontology(flights):
    assert flights.name == "Flights"
    assert len(flights.entity_types()) == 12
    flight = flights.concepts["Flight"]
    rels = {r.name: r for r in flight.relationships}
    assert rels["id"].identifying
    assert rels["canceled"].roles == []
    assert [r.concept for r in rels["registers_latitude_series"].roles] == ["DateTime", "DegreesLatitude"]
    assert flights.concepts["Airport"].relationships[2].derived


def test_referenced_builtins_are_added(flights):
    for name in ("String", "Integer", "Decimal", "DateTime", "Date"):
        assert flights.concepts[name].builtin
    assert "Float" not in flights.concepts


def test_undeclared_concepts_are_flagged():
    ontology = viz.parse_ontology(
        {
            "name": "T",
            "ontology": [
                {
                    "concept": "Person",
                    "type": "EntityType",
                    "relationships": [{"name": "employer", "roles": [{"concept": "Company"}], "verbalizes": []}],
                }
            ],
        }
    )
    company = ontology.concepts["Company"]
    assert not company.declared and not company.builtin


@pytest.mark.parametrize(
    "doc, message",
    [
        ({"name": "x"}, "no 'ontology' list"),
        ({"ontology": [{"type": "EntityType"}]}, "without a 'concept'"),
        ({"ontology": [{"concept": "A", "type": "ValueType"}] * 2}, "more than once"),
    ],
)
def test_rejects_invalid_documents(doc, message):
    with pytest.raises(viz.OntologyError, match=message):
        viz.parse_ontology(doc)


def test_html_embeds_full_model(flights):
    page = viz.to_html(flights)
    assert page.startswith("<!DOCTYPE html>")
    assert "<title>Flights ontology</title>" in page
    assert "showValues: false" in page
    assert "__" + "DATA__" not in page and "__" + "LAYOUT__" not in page
    # Self-contained: nothing is loaded from the network.
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", page)
    assert "fetch(" not in page
    assert _embedded_json(page, "ontology-layout") is None
    model = _embedded_model(page)
    names = {c["name"] for c in model["concepts"]}
    assert {"Flight", "Airport", "Route", "Delay", "String"} <= names
    route = next(c for c in model["concepts"] if c["name"] == "Route")
    destination = next(r for r in route["relationships"] if r["name"] == "destination")
    assert destination["roles"] == [{"concept": "Airport", "name": None}]
    assert destination["requires"] == ["NOT Route.departure(Airport)"]


def test_html_value_types_mode(flights):
    assert "showValues: true" in viz.to_html(flights, "nodes")


def test_html_escapes_script_breakouts():
    ontology = viz.parse_ontology(
        {"name": "<b>X</b>", "ontology": [{"concept": "A", "type": "EntityType", "description": "</script><script>alert(1)"}]}
    )
    page = viz.to_html(ontology)
    assert "</script><script>alert(1)" not in page
    assert "<title>&lt;b&gt;X&lt;/b&gt; ontology</title>" in page
    assert _embedded_model(page)["concepts"][0]["description"] == "</script><script>alert(1)"


def test_dot_inline_mode(flights):
    dot = viz.to_dot(flights)
    assert dot.startswith('digraph "Flights" {')
    assert '"Flight" -> "Route" [label="route", taillabel="*", headlabel="0..1"];' in dot
    assert '"City" -> "State" [label="state (id)"' in dot
    assert "<u>id : FlightId</u>" in dot
    assert "<i>/average_departure_delay : Delay</i>" in dot
    assert "registers_latitude_series : DateTime × DegreesLatitude" in dot
    assert '"Delay" [' not in dot


def test_dot_nodes_mode(flights):
    dot = viz.to_dot(flights, "nodes")
    assert '"Delay" [' in dot
    assert '"Capacity" -> "NrPounds" [arrowhead=empty' in dot
    assert '"Flight" -> "Delay" [label="departure_delay"' in dot


def test_cli_writes_html_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert viz.main([str(FLIGHTS)]) == 0
    out = tmp_path / "flights.ontology.html"
    assert out.exists()
    model = _embedded_model(out.read_text(encoding="utf-8"))
    assert model["name"] == "Flights"
    assert model["source"] == "flights.ontology.yaml"


def test_cli_infers_format_from_extension(tmp_path):
    out = tmp_path / "flights.dot"
    assert viz.main([str(FLIGHTS), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("digraph")


def test_cli_dot_to_stdout(capsys):
    assert viz.main([str(FLIGHTS), "-f", "dot"]) == 0
    assert capsys.readouterr().out.startswith("digraph")


def test_cli_reports_bad_input(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: nothing here\n", encoding="utf-8")
    assert viz.main([str(bad), "-o", str(tmp_path / "x.html")]) == 1
    assert "no 'ontology' list" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["examples/flights.ontology.yaml", "examples/flights.yaml"])
def test_example_ontologies_render(path):
    ontology = viz.load_ontology(_REPO / path)
    for fmt in viz.FORMATS:
        for mode in viz.VALUE_TYPE_MODES:
            assert viz.render(ontology, fmt, mode)


def _write_layout(tmp_path, nodes, **extra):
    path = tmp_path / "flights.layout.json"
    path.write_text(json.dumps({"format": "ossie-ontology-layout", "nodes": nodes, **extra}), encoding="utf-8")
    return path


def test_load_layout_normalizes_positions(tmp_path):
    path = _write_layout(
        tmp_path,
        {"Flight": {"x": 1, "y": 2.5}, "Route": {"x": -3, "y": 4, "pinned": False}},
        ontology="Flights",
        saved_at="2026-10-07T00:00:00Z",
    )
    layout = viz.load_layout(path)
    assert layout["ontology"] == "Flights"
    assert layout["saved_at"] == "2026-10-07T00:00:00Z"
    assert layout["nodes"] == {
        "Flight": {"x": 1, "y": 2.5, "pinned": True},
        "Route": {"x": -3, "y": 4, "pinned": False},
    }


@pytest.mark.parametrize(
    "content, message",
    [
        ("not json", "not valid JSON"),
        ('{"positions": {}}', "'nodes' object"),
        ('{"nodes": {"Flight": {"x": "1", "y": 2}}}', "numeric 'x' and 'y'"),
        ('{"nodes": {"Flight": {"x": true, "y": 2}}}', "numeric 'x' and 'y'"),
        ('{"nodes": {"Flight": {"x": NaN, "y": 2}}}', "numeric 'x' and 'y'"),
    ],
)
def test_load_layout_rejects_invalid_files(tmp_path, content, message):
    path = tmp_path / "bad.layout.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(viz.LayoutError, match=message):
        viz.load_layout(path)


def test_html_embeds_layout(flights, tmp_path):
    layout = viz.load_layout(_write_layout(tmp_path, {"Flight": {"x": 10, "y": 20, "pinned": True}}))
    page = viz.to_html(flights, layout=layout)
    assert _embedded_json(page, "ontology-layout")["nodes"]["Flight"] == {"x": 10, "y": 20, "pinned": True}


def test_cli_layout_option(tmp_path, capsys):
    layout = _write_layout(tmp_path, {"Flight": {"x": 10, "y": 20}, "Spaceship": {"x": 0, "y": 0}})
    out = tmp_path / "out.html"
    assert viz.main([str(FLIGHTS), "--layout", str(layout), "-o", str(out)]) == 0
    assert "ignoring unknown concepts: Spaceship" in capsys.readouterr().err
    assert "Flight" in _embedded_json(out.read_text(encoding="utf-8"), "ontology-layout")["nodes"]


def test_cli_reports_bad_layout(tmp_path, capsys):
    bad = tmp_path / "bad.layout.json"
    bad.write_text("[]", encoding="utf-8")
    assert viz.main([str(FLIGHTS), "--layout", str(bad), "-o", str(tmp_path / "x.html")]) == 1
    assert "'nodes' object" in capsys.readouterr().err
