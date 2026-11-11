from converter.config import Settings
from converter.formats import ext_of, safe_filename, stem_of


def test_ext_of_normalizes_aliases_and_compounds():
    assert ext_of("Foto.JPEG") == "jpg"
    assert ext_of("backup.tgz") == "tar.gz"
    assert ext_of("backup.tar.gz") == "tar.gz"
    assert ext_of("README") == ""


def test_stem_of():
    assert stem_of("a/b/backup.tar.gz") == "backup"
    assert stem_of("C:\\x\\relazione.docx") == "relazione"
    assert stem_of(".docx") == "file"


def test_safe_filename_strips_paths_and_keeps_extension():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename(None) == "file"
    assert safe_filename("..") == "file"
    long = "a" * 300 + ".tar.gz"
    out = safe_filename(long)
    assert len(out) == 200 and out.endswith(".tar.gz")


def test_settings_from_env(tmp_path):
    (tmp_path / "disabled.json").write_text('[["png", "avif"]]')
    s = Settings.from_env({"WORK_DIR": str(tmp_path), "MAX_PARALLEL": "0", "MAX_UPLOAD_GB": "0.5",
                           "DISABLED_CONVERSIONS": "heic>avif; .PDF > epub"})
    assert s.max_parallel == 1
    assert s.max_upload_bytes == 512 * 1024**2
    assert s.disabled == {("heic", "avif"), ("pdf", "epub"), ("png", "avif")}
