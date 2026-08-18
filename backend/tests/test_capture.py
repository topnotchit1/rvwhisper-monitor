import os

from rv_dashboard.capture import load_env_file, safe_name


def test_load_env_file_reads_simple_values_without_overwriting_environment(tmp_path, monkeypatch):
    env_file = tmp_path / "dashboard.env"
    env_file.write_text("RVW_ID=sample-id\nRVW_USERNAME='sample-user'\n# ignored\n", encoding="utf-8")
    monkeypatch.setenv("RVW_ID", "already-set")

    load_env_file(env_file)

    assert os.environ["RVW_ID"] == "already-set"
    assert os.environ["RVW_USERNAME"] == "sample-user"


def test_safe_name_removes_path_characters():
    assert safe_name("Dog Area / Inside", "sensor") == "dog-area-inside"
    assert safe_name("///", "sensor-01") == "sensor-01"
