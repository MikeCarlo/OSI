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

"""Browser tests for the standalone ontology viewer (ontology/visualize/ontology-viewer.html).

The page runs in a headless Chrome/Edge/Chromium and posts its results back to a local HTTP
server. Set OSSIE_TEST_BROWSER to choose the browser executable; the tests are skipped when no
browser is found.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_HERE = Path(__file__).parent
_REPO = _HERE.parents[2]
VIEWER = _HERE.parent / "ontology-viewer.html"
FLIGHTS = _REPO / "examples" / "flights.ontology.yaml"

BUILTINS = {
    "Any": "EntityType",
    "Boolean": "ValueType",
    "Date": "ValueType",
    "DateTime": "ValueType",
    "Decimal": "ValueType",
    "Float": "ValueType",
    "Integer": "ValueType",
    "String": "ValueType",
}

# Hand-written documents covering the YAML subset the viewer reads; each must match PyYAML.
YAML_CASES = {
    "block_scalars": "a: |\n  line1\n  line2\nb: >\n  folded\n  text\n\n  para\nc: |-\n  strip\nd: |+\n  keep\n\ne: end\n",
    "flow": "a: [1, 2.5, 'x', \"y\", true, null, ~]\nb: {k: v, n: [1, {m: 2}]}\nc: [\n  one,\n  two,\n]\nd: []\ne: {}\n",
    "quotes": (
        "a: 'it''s # not a comment'\nb: \"tab\\tnew\\nline \\u00e9\"\nc: plain # comment\n"
        "d: 'multi\n  line'\ne: \"x: y\"\nf: \"a\n\n  b\"\n"
    ),
    "sequences": "top:\n- a\n- b:\n    c: 1\n  d: 2\n- - nested\n  - seq\n-\n  e: 3\nindented:\n  - x\n  - y\n",
    "scalars": (
        "i: 42\nneg: -7\nf: 3.14\nexp: 1.0e+3\nstr: 1e3\nver: 0.2.0.dev0\ny: yes\nn: off\nhex: 0x1F\n"
        "oct: 017\nnull1:\nempty: ''\ndate: 2026-01-01\nurl: http://example.com/a#b\ncolon: a:b\n"
    ),
    "multiline_plain": "desc: this is a long\n  plain scalar\n  over lines\nnext: x\n",
    "comments_and_markers": "# leading\n---\na: 1 # trailing\n\n# middle\nb:\n  # inside\n  c: 2\n...\n",
    "quoted_keys": "\"quoted key\": 1\n'single': 2\nkey with spaces: 3\n",
    "unicode": "name: Café ✈\nlist: [ü, \"→\"]\n",
    "json_inline": '{"a": [1, 2, {"b": null}], "c": "d"}',
    "json_multiline": '{\n  "a": 1,\n  "b": [\n    true\n  ]\n}\n',
    "empty_values": "a:\nb: ~\nc: []\nd:\n  - \n  - x\n",
    "deep_indent": "a:\n    b:\n        - c: 1\n          d: [x]\n",
    "crlf": "a: 1\r\nb:\r\n  - x\r\n",
}

# Documents the viewer rejects, with the expected error text.
YAML_ERRORS = {
    "a: &x 1\nb: *x\n": "line 1: anchors and aliases are not supported",
    "a: !!str 1\n": "line 1: tags are not supported",
    "a:\n\tb: 1\n": "line 2: tabs are not allowed",
    "a: [1, 2\nb: 3\n": 'line 1: unclosed "["',
    "a: 1\na: 2\n": 'line 2: duplicate key "a"',
    "a: 1\n  b: 2\n": "line 2: unexpected indentation",
    "a: 1\n---\nb: 2\n": "line 2: multiple YAML documents are not supported",
    "a: 'unclosed\n": "line 1: unclosed quoted string",
}

TINY = "name: Tiny\nontology:\n- concept: A\n  type: EntityType\n"
TINY2 = TINY + (
    "- concept: B\n  type: EntityType\n  relationships:\n  - name: a\n"
    "    roles: [{concept: A}]\n    verbalizes: ['{B} has {A}']\n    multiplicity: ManyToOne\n"
)

# Runs before the viewer: pretend flights.ontology.yaml was opened on a previous visit.
_SEED_SCRIPT = """<script id="seed" type="application/json">{seed}</script>
<script>
localStorage.clear();
localStorage.setItem("ossie-ontology-viewer:last-opened", document.getElementById("seed").textContent);
</script>"""

_TEST_SCRIPT = r"""
<script>
window.__errors = [];
addEventListener("error", e => __errors.push(String(e.message)));
addEventListener("unhandledrejection", e => __errors.push(String(e.reason)));
addEventListener("load", () => setTimeout(async () => {
  const results = { errors: __errors };
  try {
    const cases = JSON.parse(document.getElementById("test-cases").textContent);
    const attempt = fn => { try { return { value: fn() }; } catch (e) { return { error: String(e.message) }; } };
    results.yaml = Object.fromEntries(Object.entries(cases.yaml).map(([k, text]) => [k, attempt(() => OssieYaml.parse(text))]));
    results.yamlErrors = cases.yamlErrors.map(text => attempt(() => OssieYaml.parse(text)));
    results.ontologies = Object.fromEntries(Object.entries(cases.ontologies).map(
      ([name, text]) => [name, attempt(() => OssieOntology.fromText(text, name))]));
    results.ui = await uiTests(cases);
  } catch (e) { results.fatal = String(e && e.stack || e); }
  results.errors = __errors;
  await fetch("/results", { method: "POST", body: JSON.stringify(results) });
}, 200));

async function uiTests(cases) {
  const $ = id => document.getElementById(id), r = {};
  const wait = ms => new Promise(res => setTimeout(res, ms));
  const pos = id => document.querySelector(`.node[data-id="${id}"]`)?.getAttribute("transform") ?? null;
  const nodeIds = () => [...document.querySelectorAll(".node")].map(n => n.dataset.id).sort();
  const status = () => $("status").textContent;

  await ossieViewer.ready;
  r.reopened = { title: document.title, status: status(), nodes: nodeIds().length,
    emptyHidden: $("empty").hidden, chip: $("source").hidden ? null : $("source").textContent };

  const menu = $("layoutItems"), button = $("layoutButton");
  r.menu = { initiallyHidden: menu.hidden };
  button.click();
  r.menu.opens = !menu.hidden && button.getAttribute("aria-expanded") === "true";
  r.menu.focusFirst = document.activeElement === $("saveLayout");
  r.menu.items = [...menu.querySelectorAll('[role="menuitem"]')].map(b => b.firstChild.textContent.trim());
  menu.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  r.menu.closesOnEscape = menu.hidden && button.getAttribute("aria-expanded") === "false";
  button.click(); $("relayout").click();
  r.menu.closesOnItem = menu.hidden;
  r.menu.resetStatus = status();
  button.click(); document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  r.menu.closesOnOutsideClick = menu.hidden;

  const before = pos("Flight");
  const opened = await ossieViewer.openText(cases.flightsPlus, "flights.edit.yaml");
  r.sameOntology = { opened, title: document.title, flightKept: pos("Flight") === before,
    hasGate: !!pos("Gate"), chip: $("source").hidden ? null : $("source").textContent,
    remembered: JSON.parse(localStorage.getItem("ossie-ontology-viewer:last-opened")).name };

  const bad = await ossieViewer.openText("name: Broken\nontology:\n- concept: [A\n", "broken.yaml");
  r.invalid = { opened: bad, status: status(), isError: $("status").classList.contains("error"), keptGate: !!pos("Gate") };

  $("closeOpened").click();
  r.closed = { emptyVisible: !$("empty").hidden, chipHidden: $("source").hidden, nodes: nodeIds(),
    title: document.title, status: status(),
    forgotten: localStorage.getItem("ossie-ontology-viewer:last-opened") === null };
  $("relayout").click();
  r.closed.resetWhileEmpty = status();

  await ossieViewer.openText(cases.tiny, "tiny.yaml");
  r.other = { title: document.title, nodes: nodeIds(), model: ossieViewer.model.name };

  let content = cases.tiny, modified = 1;
  // A plain object rather than a File: Blob reads run in real time, but the headless browser
  // fast-forwards timers (--virtual-time-budget), so waits would end before a Blob read finishes.
  const handle = { kind: "file", name: "tiny.yaml",
    getFile: async () => ({ name: "tiny.yaml", lastModified: modified, text: async () => content }) };
  await ossieViewer.openHandle(handle);
  r.watch = { live: !!document.querySelector("#source .live") };
  content = cases.tiny2; modified = 2;
  await wait(2500);
  r.watch.afterChange = nodeIds();
  r.watch.status = status();
  content = "name: Tiny\nontology: [\n"; modified = 3;
  await wait(2500);
  r.watch.brokenStatus = status();
  r.watch.afterBroken = nodeIds();
  content = cases.tiny; modified = 4;
  await wait(2500);
  r.watch.recovered = nodeIds();
  ossieViewer.close();
  r.watch.stoppedOnClose = !document.querySelector("#source .live") && !$("empty").hidden;

  // Last, because toggling value types starts a re-layout animation.
  await ossieViewer.openText(cases.flightsPlus, "flights.edit.yaml");
  const builtins = $("showBuiltins"), values = $("showValues");
  r.builtinsToggle = { initiallyDisabled: builtins.disabled && $("builtinsLabel").classList.contains("disabled") };
  values.click();
  r.builtinsToggle.enabledWithValues = !builtins.disabled && !$("builtinsLabel").classList.contains("disabled");
  builtins.click();
  r.builtinsToggle.showsString = !!pos("String");
  values.click();
  r.builtinsToggle.disabledAgain = builtins.disabled && builtins.checked;
  r.builtinsToggle.hidesString = !pos("String");
  return r;
}
</script>
"""


def _find_browser() -> str | None:
    if os.environ.get("OSSIE_TEST_BROWSER"):
        return os.environ["OSSIE_TEST_BROWSER"]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        if path := shutil.which(name):
            return path
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    return next((c for c in candidates if os.path.exists(c)), None)


def _run_in_browser(browser: str, page: str, timeout: float = 120) -> dict:
    done, box = threading.Event(), {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            box["results"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(204)
            self.end_headers()
            done.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Edge's launcher on Windows may hand over to a detached process and exit straight away, so
    # completion is signalled by the POST rather than by the process exiting.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        args = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            f"--screenshot={Path(profile) / 'page.png'}",
            "--virtual-time-budget=120000",
            f"http://127.0.0.1:{server.server_address[1]}/",
        ]
        if sys.platform.startswith("linux"):
            args.insert(1, "--no-sandbox")
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            finished = done.wait(timeout)
        finally:
            server.shutdown()
            if proc.poll() is None:
                proc.kill()
                proc.wait(10)
    if not finished:
        pytest.fail(f"browser did not report results within {timeout}s ({browser})")
    return box["results"]


def _as_json(value):
    return json.loads(json.dumps(value, default=str))


def _script_json(value) -> str:
    # Escaping "<" keeps "</script>" inside the data from ending the script element.
    return json.dumps(value).replace("<", "\\u003c")


def _str_list(value) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def _expected_model(doc: dict) -> dict:
    """Reference interpretation of an ontology document (see ontology/ontology.md)."""
    concepts = {}
    for comp in doc["ontology"]:
        identify_by = _str_list(comp.get("identify_by"))
        rels = [
            {
                "name": str(rel["name"]),
                "roles": [
                    {"concept": str(r["concept"]), "name": r.get("name")}
                    for r in rel.get("roles") or []
                    if isinstance(r, dict) and "concept" in r
                ],
                "multiplicity": rel.get("multiplicity"),
                "description": rel.get("description"),
                "verbalizes": _str_list(rel.get("verbalizes")),
                "derived_by": _str_list(rel.get("derived_by")),
                "requires": _str_list(rel.get("requires")),
                "iri": rel.get("iri"),
                "identifying": str(rel["name"]) in identify_by,
            }
            for rel in comp.get("relationships") or []
        ]
        concepts[comp["concept"]] = {
            "name": comp["concept"],
            "type": comp.get("type", "Unknown"),
            "builtin": False,
            "declared": True,
            "description": comp.get("description"),
            "extends": _str_list(comp.get("extends")),
            "identify_by": identify_by,
            "requires": _str_list(comp.get("requires")),
            "derived_by": _str_list(comp.get("derived_by")),
            "iri": comp.get("iri"),
            "relationships": rels,
        }
    referenced = []
    for c in list(concepts.values()):
        referenced += c["extends"]
        referenced += [role["concept"] for r in c["relationships"] for role in r["roles"]]
    for ref in referenced:
        if ref not in concepts:
            concepts[ref] = {
                "name": ref,
                "type": BUILTINS.get(ref, "Unknown"),
                "builtin": ref in BUILTINS,
                "declared": ref in BUILTINS,
                "description": None,
                "extends": [],
                "identify_by": [],
                "requires": [],
                "derived_by": [],
                "iri": None,
                "relationships": [],
            }
    return {
        "name": str(doc.get("name", "Ontology")),
        "description": doc.get("description"),
        "requires": _str_list(doc.get("requires")),
        "concepts": list(concepts.values()),
    }


def _flights_plus_gate() -> str:
    doc = yaml.safe_load(FLIGHTS.read_text(encoding="utf-8"))
    doc["ontology"].append(
        {
            "concept": "Gate",
            "type": "EntityType",
            "relationships": [
                {"name": "at", "roles": [{"concept": "Airport"}], "verbalizes": ["{Gate} is at {Airport}"]}
            ],
        }
    )
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def _example_documents() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((_REPO / "examples").glob("*.yaml"))}


@pytest.fixture(scope="module")
def results():
    browser = _find_browser()
    if not browser:
        pytest.skip("no Chrome, Edge or Chromium found (set OSSIE_TEST_BROWSER)")
    flights_text = FLIGHTS.read_text(encoding="utf-8")
    cases = {
        "yaml": {**YAML_CASES, **_example_documents()},
        "yamlErrors": list(YAML_ERRORS),
        "ontologies": {
            "flights.ontology.yaml": flights_text,
            "flights.yaml": (_REPO / "examples" / "flights.yaml").read_text(encoding="utf-8"),
            "flights.json": json.dumps(yaml.safe_load(flights_text)),
            "flights.dumped.yaml": _flights_plus_gate(),
            "no_ontology.yaml": "name: x\n",
            "duplicate.yaml": "ontology:\n- {concept: A, type: EntityType}\n- {concept: A, type: ValueType}\n",
        },
        "flightsPlus": _flights_plus_gate(),
        "tiny": TINY,
        "tiny2": TINY2,
    }
    page = VIEWER.read_text(encoding="utf-8")
    seed = _SEED_SCRIPT.replace("{seed}", _script_json({"name": FLIGHTS.name, "text": flights_text}))
    page = page.replace("<head>", "<head>" + seed, 1)
    tests = f'<script id="test-cases" type="application/json">{_script_json(cases)}</script>{_TEST_SCRIPT}'
    page = page.replace("</body>", tests + "</body>")
    data = _run_in_browser(browser, page)
    assert "fatal" not in data, data.get("fatal")
    data["_cases"] = cases
    return data


def test_viewer_is_self_contained():
    page = VIEWER.read_text(encoding="utf-8")
    assert not re.search(r"<script[^>]*\ssrc=", page)
    assert not re.search(r"<link[^>]*stylesheet", page)
    assert "fetch(" not in page and "XMLHttpRequest" not in page
    assert not re.search(r"__[A-Z_]+__", page), "leftover template placeholder"


def test_page_has_no_script_errors(results):
    assert results["errors"] == []


@pytest.mark.parametrize("name", list(YAML_CASES) + sorted(_example_documents()))
def test_yaml_reader_matches_pyyaml(results, name):
    expected = _as_json(yaml.safe_load(results["_cases"]["yaml"][name]))
    assert results["yaml"][name] == {"value": expected}


@pytest.mark.parametrize("index, text", list(enumerate(YAML_ERRORS)))
def test_yaml_reader_reports_unsupported_or_invalid_input(results, index, text):
    assert YAML_ERRORS[text] in results["yamlErrors"][index].get("error", "")


@pytest.mark.parametrize("name", ["flights.ontology.yaml", "flights.yaml", "flights.json", "flights.dumped.yaml"])
def test_ontology_model(results, name):
    expected = _as_json(_expected_model(yaml.safe_load(results["_cases"]["ontologies"][name])))
    assert results["ontologies"][name] == {"value": expected}


def test_flights_model_details(results):
    model = results["ontologies"]["flights.ontology.yaml"]["value"]
    concepts = {c["name"]: c for c in model["concepts"]}
    assert sum(c["type"] == "EntityType" and not c["builtin"] for c in concepts.values()) == 12
    assert {n for n, c in concepts.items() if c["builtin"]} == {"String", "Integer", "Decimal", "DateTime", "Date"}
    flight = {r["name"]: r for r in concepts["Flight"]["relationships"]}
    assert flight["id"]["identifying"] and not flight["route"]["identifying"]
    assert flight["canceled"]["roles"] == []
    assert [r["concept"] for r in flight["registers_latitude_series"]["roles"]] == ["DateTime", "DegreesLatitude"]


def test_ontology_errors(results):
    assert "no 'ontology' list" in results["ontologies"]["no_ontology.yaml"]["error"]
    assert "concept 'A' is declared more than once" in results["ontologies"]["duplicate.yaml"]["error"]


def test_reopens_last_ontology_on_next_visit(results):
    reopened = results["ui"]["reopened"]
    assert reopened["title"] == "Flights – Ossie ontology viewer"
    assert reopened["status"] == "Reopened flights.ontology.yaml from your last visit"
    assert reopened["nodes"] == 12 and reopened["emptyHidden"]
    assert "flights.ontology.yaml" in reopened["chip"]


def test_layout_menu(results):
    menu = results["ui"]["menu"]
    assert menu["initiallyHidden"] and menu["opens"] and menu["focusFirst"]
    assert menu["items"] == ["Save layout", "Load layout…", "Reset layout"]
    assert menu["closesOnEscape"] and menu["closesOnItem"] and menu["closesOnOutsideClick"]
    assert menu["resetStatus"] == "Reset to the automatic layout"


def test_open_same_ontology_keeps_positions(results):
    opened = results["ui"]["sameOntology"]
    assert opened["opened"] is True
    assert opened["title"] == "Flights – Ossie ontology viewer"
    assert opened["flightKept"] and opened["hasGate"]
    assert "flights.edit.yaml" in opened["chip"]
    assert opened["remembered"] == "flights.edit.yaml"


def test_open_invalid_file_reports_error_and_keeps_graph(results):
    invalid = results["ui"]["invalid"]
    assert invalid["opened"] is False
    assert invalid["isError"] and invalid["keptGate"]
    assert invalid["status"].startswith("Could not read broken.yaml: line 3:")


def test_close_shows_empty_viewer(results):
    assert results["ui"]["closed"] == {
        "emptyVisible": True,
        "chipHidden": True,
        "nodes": [],
        "title": "Ossie ontology viewer",
        "status": "Closed flights.edit.yaml",
        "forgotten": True,
        "resetWhileEmpty": "Open an ontology first",
    }


def test_open_other_ontology(results):
    assert results["ui"]["other"] == {"title": "Tiny – Ossie ontology viewer", "nodes": ["A"], "model": "Tiny"}


def test_watched_file_reloads_on_change(results):
    watch = results["ui"]["watch"]
    assert watch["live"]
    assert watch["afterChange"] == ["A", "B"] and watch["status"] == "Reloaded tiny.yaml"
    assert watch["brokenStatus"].startswith("Could not read tiny.yaml: line 2:")
    assert watch["afterBroken"] == ["A", "B"]
    assert watch["recovered"] == ["A"]
    assert watch["stoppedOnClose"]


def test_builtins_toggle_requires_value_types(results):
    assert results["ui"]["builtinsToggle"] == {
        "initiallyDisabled": True,
        "enabledWithValues": True,
        "showsString": True,
        "disabledAgain": True,
        "hidesString": True,
    }
