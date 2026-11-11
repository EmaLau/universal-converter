from converter.graph import default_graph, is_sensible
from converter.tools import csv_separator, ffmpeg_attempts


def tools_of(plan):
    return [(e.tool, e.src, e.dst) for e in plan]


def test_multi_step_plan():
    g = default_graph()
    assert tools_of(g.plan("md", "pdf")) == [("Pandoc", "md", "docx"), ("LibreOffice", "docx", "pdf")]
    assert g.plan("markdown", "pdf") == g.plan("md", "pdf")  # alias


def test_pdf_to_docx_only_from_original_pdf():
    g = default_graph()
    assert tools_of(g.plan("pdf", "docx")) == [("pdf2docx", "pdf", "docx")]
    # docx -> pdf -> docx non deve passare da pdf2docx: c'e' gia' la conversione diretta
    assert all(e.tool != "pdf2docx" for e in g.plan("docx", "odt"))


def test_nonsense_conversions_are_hidden():
    g = default_graph()
    assert g.plan("xlsx", "mp3") is None
    assert g.plan("mp3", "pdf") is None
    assert g.plan("zip", "pdf") is None
    assert not is_sensible("pptx", "docx")
    assert is_sensible("gif", "mp4")


def test_multi_file_outputs_are_final():
    g = default_graph()
    plan = g.plan("pdf", "jpg")
    assert plan[-1].final_only and len(plan) == 1
    assert g.plan("pdf", "webp") is None or all(not e.final_only for e in g.plan("pdf", "webp")[:-1])


def test_disable_removes_edges():
    g = default_graph(disabled=[("png", "avif")])
    assert all((e.src, e.dst) != ("png", "avif") for e in (g.plan("png", "avif") or []))
    assert "avif" in g.targets("jpg")


def test_payload_contains_aliases():
    p = default_graph().payload()
    assert p["inputs"]["jpeg"] == p["inputs"]["jpg"]
    assert "LibreOffice" in p["tools"]


def test_csv_separator():
    assert csv_separator("a;b;c\n1;2;3", "csv") == 59
    assert csv_separator("a,b\n1,2", "csv") == 44
    assert csv_separator("a,b", "tsv") == 9


def test_ffmpeg_attempts_copy_first_when_possible():
    assert ffmpeg_attempts("mp4", "h264", "aac")[0][-4:] == ["-c", "copy", "-movflags", "+faststart"]
    assert ffmpeg_attempts("mp4", "vp9", "opus")[0][:2] == ["-c:v", "libx264"]
    assert ffmpeg_attempts("mkv", "vp9", "opus")[0] == ["-map", "0", "-c", "copy"]
    assert ffmpeg_attempts("mp3", "", "")[0][0] == "-vn"
