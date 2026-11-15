"""Smoke tests : chaque module Python du dépôt s'importe sans exécuter `main`,
plus un test unitaire simple par outil quand c'est évident.

Chargement par importlib + sys.path plutôt que par import statique : mypy_path =
"tools,scripts" résout déjà ces fichiers sous leur basename, et un import
package-style les ferait apparaître deux fois sous deux noms de module pour mypy.
"""

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL_MODULES = ("dashboard", "spec_ingest", "specs_fetch", "specs_qa", "usage_report")
LIB_MODULES = ("filemap_core", "hook_payload", "scan_report")


def load_module(name: str, subdir: str) -> ModuleType:
    """Importe `name` depuis ROOT/subdir (ajouté à sys.path) sans exécuter main."""
    directory = ROOT / subdir
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return importlib.import_module(name)


def fn(mod: ModuleType, name: str) -> Any:
    """Attribut de module résolu dynamiquement (mypy voit Any, pas de conflit de noms)."""
    return vars(mod)[name]


@pytest.fixture(scope="module")
def tools() -> dict[str, ModuleType]:
    """Tous les modules de tools/, importés."""
    return {name: load_module(name, "tools") for name in TOOL_MODULES}


@pytest.fixture(scope="module")
def libs() -> dict[str, ModuleType]:
    """Tous les modules de scripts/ci/lib/, importés."""
    return {name: load_module(name, "scripts/ci/lib") for name in LIB_MODULES}


def test_smoke_import_tools(tools: dict[str, ModuleType]) -> None:
    for name, mod in tools.items():
        assert mod.__name__ == name
        assert callable(fn(mod, "main")), f"{name} n'a pas de main()"


def test_smoke_import_libs(libs: dict[str, ModuleType]) -> None:
    for name, mod in libs.items():
        assert mod.__name__ == name
        assert callable(fn(mod, "main")), f"{name} n'a pas de main()"


def test_dashboard_helpers(tools: dict[str, ModuleType]) -> None:
    d = tools["dashboard"]
    assert fn(d, "parse_iso")("2026-11-15T10:00:00+00:00") is not None
    assert fn(d, "parse_iso")("garbage") is None
    assert fn(d, "fmt_dur")(3723) == "1h02m03s"
    assert fn(d, "fmt_dur")(63) == "1m03s"
    assert fn(d, "fmt_dur")(None) == "-"
    assert fn(d, "fmt_ts")("2026-11-15T10:00:00+00:00") == "15/11 10:00:00"
    assert fn(d, "fmt_ts")(None) == "-"
    assert fn(d, "bar")(0.5) == "#" * 9 + "-" * 9
    found: dict[str, float] = {}
    fn(d, "find_usage")({"a": {"input_tokens": 3, "lst": [{"output_tokens": 2}]}}, found)
    assert found == {"input_tokens": 3.0, "output_tokens": 2.0}
    model = fn(d, "resolve_model")("m", {"m": {"name": "M", "input_price": 1.0}}, {}, 100)
    assert model["name"] == "M"
    assert model["source"] == "local"
    assert model["auto_compact_threshold"] == 100
    usage = dict.fromkeys(fn(d, "USAGE_KEYS"), 0.0) | {"input_tokens": 1000.0, "output_tokens": 10.0}
    prices = {"input_price": 2.0, "output_price": 10.0, "cached_input_price": None}
    cost = fn(d, "est_cost")(usage, prices)
    assert cost == pytest.approx(0.0021)
    assert fn(d, "est_cost")(usage, {"input_price": None, "output_price": None, "cached_input_price": None}) is None


def test_dashboard_collect_render(tmp_path: Path, tools: dict[str, ModuleType]) -> None:
    d = tools["dashboard"]
    vibe = tmp_path / "vibe"
    sid = "abcdef12"
    journal = vibe / "logs" / "session" / "unified" / sid / "journal"
    journal.mkdir(parents=True)
    (vibe / "logs" / "session" / "active").mkdir(parents=True)
    (vibe / "config.toml").write_text(
        'auto_compact_threshold = 200000\n[[models]]\nalias = "test-model"\n'
        'name = "Test Model"\ninput_price = 2.0\noutput_price = 10.0\n',
        encoding="utf-8",
    )
    (vibe / "logs" / "session" / "unified" / sid / "meta.json").write_text(
        json.dumps(
            {
                "session_id": sid,
                "start_time": "2026-11-15T10:00:00+00:00",
                "config": {"active_model": "test-model"},
                "environment": {"working_directory": "/tmp/cpm-store"},
                "stats": {"session_total_llm_tokens": 55, "session_cost": 0.001},
            }
        ),
        encoding="utf-8",
    )
    (journal / "j.jsonl").write_text(
        json.dumps({"payload": {"usage": {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55}}}) + "\n",
        encoding="utf-8",
    )
    sessions, thr = fn(d, "collect")(vibe)
    assert thr == 200000
    assert len(sessions) == 1
    s = sessions[0]
    assert s["short"] == sid
    assert s["ctx_now"] == 50
    assert s["model"]["name"] == "Test Model"
    assert s["calls"] == 1
    text = fn(d, "render_text")(sessions, thr, None)
    assert sid in text and "TOTAUX" in text
    html = fn(d, "render_html")(sessions, thr, None)
    assert "Vibe usage dashboard" in html and sid in html
    # filtre projet : aucun cwd ne contient "other"
    assert fn(d, "collect")(vibe, "other") == ([], 200000)


def test_usage_report_helpers(tmp_path: Path, tools: dict[str, ModuleType]) -> None:
    u = tools["usage_report"]
    models = fn(u, "resolve_models")({"models": [{"alias": "a", "input_price": 1}, {"nope": 1}]})
    assert models == {"a": {"alias": "a", "input_price": 1, "name": "a"}}
    models2 = fn(u, "resolve_models")({"models": {"b": {"provider": "x"}}})
    assert models2["b"]["name"] == "b"
    assert models2["b"]["alias"] == "b"
    assert fn(u, "load_session_meta")(tmp_path / "absent.json") is None
    meta = tmp_path / "m.json"
    meta.write_text('{"session_id": "s1"}', encoding="utf-8")
    assert fn(u, "load_session_meta")(meta) == {"session_id": "s1"}

    root = tmp_path / "logs" / "session"
    journal = root / "unified" / "s1" / "journal"
    journal.mkdir(parents=True)
    (root / "unified" / "s1" / "meta.json").write_text(
        json.dumps({"config": {"active_model": "a", "models": [{"alias": "a", "name": "Model A"}]}}),
        encoding="utf-8",
    )
    (journal / "j.jsonl").write_text(
        json.dumps({"payload": {"usage": {"input_tokens": 7, "total_tokens": 7}}}) + "\nligne invalide\n",
        encoding="utf-8",
    )
    per_model, n_calls = fn(u, "llm_call_usage")(root)
    assert n_calls == 1
    assert per_model["Model A"]["calls"] == 1
    assert per_model["Model A"]["input_tokens"] == 7


def test_specs_qa_helpers(tools: dict[str, ModuleType]) -> None:
    q = tools["specs_qa"]
    assert fn(q, "norm_hard")("Hello, World! 123") == "helloworld123"
    sents = fn(q, "sentences")("Court. Une phrase vraiment beaucoup plus longue que quarante caractères !")
    assert len(sents) == 1


def test_specs_fetch_rejects_non_https(tools: dict[str, ModuleType]) -> None:
    f = tools["specs_fetch"]
    with pytest.raises(ValueError):
        fn(f, "https_get")("http://example.com/x.pdf")


def test_spec_ingest_ocr_pdf(tmp_path: Path, tools: dict[str, ModuleType]) -> None:
    ing = tools["spec_ingest"]
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    class Uploaded:
        id = "f1"

    class Signed:
        url = "https://signed.example/f1"

    class Files:
        def upload(self, file: dict[str, object]) -> Uploaded:
            assert file["file_name"] == "doc.pdf"
            return Uploaded()

        def get_signed_url(self, file_id: str) -> Signed:
            assert file_id == "f1"
            return Signed()

        def delete(self, file_id: str) -> None:
            assert file_id == "f1"

    class Page:
        markdown = "# page"

    class Resp:
        pages = [Page()]

    class Ocr:
        def process(self, model: str, document: dict[str, str], include_image_base64: bool) -> Resp:
            assert document == {"type": "file", "file_uri": "https://signed.example/f1"}
            assert include_image_base64 is True
            return Resp()

    class Client:
        files = Files()
        ocr = Ocr()

    resp = fn(ing, "ocr_pdf")(Client(), pdf)
    assert resp.pages[0].markdown == "# page"


def test_hook_payload(libs: dict[str, ModuleType]) -> None:
    hp = libs["hook_payload"]
    assert fn(hp, "_payload")('{"cwd": "/tmp"}') == {"cwd": "/tmp"}
    assert fn(hp, "_payload")("not json") == {}
    assert fn(hp, "written_file")('{"tool_input": {"file_path": "/x/y.py"}}') == "/x/y.py"
    assert fn(hp, "written_file")('{"tool_input": {"filePath": "/z.py"}}') == "/z.py"


def test_scan_report(libs: dict[str, ModuleType]) -> None:
    sr = libs["scan_report"]
    tool = fn(sr, "TOOLS")["bandit"]
    report = json.dumps(
        {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "test_id": "B601",
                    "filename": "./a/b.py",
                    "line_number": 3,
                    "issue_text": "bad | thing",
                }
            ]
        }
    )
    findings = fn(sr, "parse_report")(tool, report)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "HIGH"
    assert finding.rule == "B601"
    assert finding.location == "a/b.py:3"
    assert "|" not in finding.issue
    rendered = fn(sr, "render")(tool, findings)
    assert "| HIGH | `B601` | `a/b.py:3`" in rendered


def test_filemap_split_sections(libs: dict[str, ModuleType]) -> None:
    fm = libs["filemap_core"]
    text = "préambule perdu\n# ── Python ──\nligne 1\nligne 2\n# ── Rust ──\nrust 1\n"
    sections = fn(fm, "split_sections")(text)
    assert sections == [("Python", ["ligne 1", "ligne 2"]), ("Rust", ["rust 1", ""])]
