import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench import load_test


def test_ollama_model_processor_is_read_from_installed_model_table(monkeypatch):
    monkeypatch.setattr(load_test.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(
        load_test.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=(
                "NAME ID SIZE PROCESSOR CONTEXT UNTIL\n"
                "qwen3:1.7b 8f68893c685c 1.9 GB 100% GPU 4096 2 minutes from now\n"
            ),
            stderr="",
        ),
    )

    assert load_test.ollama_model_processor("qwen3:1.7b") == "100% GPU"
