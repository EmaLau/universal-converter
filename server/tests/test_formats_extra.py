import json

import pytest

from converter.graph import default_graph
from converter.tools import convert_data, to_rows

yaml = pytest.importorskip("yaml")


def test_new_categories_stay_separate():
    g = default_graph()
    assert g.plan("srt", "vtt") and g.plan("srt", "pdf") is None
    assert g.plan("ttf", "woff2") and g.plan("ttf", "otf") is None and g.plan("woff2", "ttf")
    assert g.plan("json", "pdf") is None
    assert [e.tool for e in g.plan("json", "xlsx")] == ["Python", "LibreOffice"]
    assert g.plan("docx", "pptx") is None and g.plan("md", "pptx")


def test_docx_to_txt_avoids_libreoffice():
    assert [e.tool for e in default_graph().plan("docx", "txt")] == ["Pandoc"]


def test_to_rows_flattens_wrapper_and_nested_values():
    cols, rows = to_rows({"persone": [{"nome": "Anna", "tag": ["a"]}, {"nome": "Luca", "eta": 2}]})
    assert cols == ["nome", "tag", "eta"]
    assert rows[0]["tag"] == '["a"]'


def test_convert_data_roundtrip(tmp_path):
    src = tmp_path / "a.csv"
    src.write_text("nome;eta\nAnna;30\n")
    out = tmp_path / "a.json"
    convert_data(src, out, "csv", "json")
    assert json.loads(out.read_text()) == [{"nome": "Anna", "eta": "30"}]
    y = tmp_path / "a.yaml"
    convert_data(out, y, "json", "yaml")
    assert yaml.safe_load(y.read_text()) == [{"nome": "Anna", "eta": "30"}]


def test_convert_data_reports_invalid_input(tmp_path):
    from converter.runner import ConvError
    bad = tmp_path / "x.json"
    bad.write_text("{non json")
    with pytest.raises(ConvError, match="non valido"):
        convert_data(bad, tmp_path / "x.yaml", "json", "yaml")
