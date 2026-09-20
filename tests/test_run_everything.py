import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from run_everything import detect_enrichment  # noqa: E402


def test_explicit_mode_passes_through():
    assert detect_enrichment("claude") == "claude"
    assert detect_enrichment("ollama") == "ollama"
    assert detect_enrichment("skip") == "skip"


def test_auto_picks_ollama_when_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert detect_enrichment("auto") == "ollama"


def test_auto_picks_ollama_when_key_is_still_the_placeholder(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-...")
    assert detect_enrichment("auto") == "ollama"


def test_auto_picks_claude_when_a_real_looking_key_is_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-realkeyvalue")
    assert detect_enrichment("auto") == "claude"
