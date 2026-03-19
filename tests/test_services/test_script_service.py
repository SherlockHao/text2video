import pytest

from app.services.script_service import (
    check_sensitive_words,
    reload_blocklist,
    validate_script_input,
    _cached_words,
)
import app.services.script_service as script_service_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure blocklist cache is cleared before each test."""
    script_service_mod._cached_words = None
    yield
    script_service_mod._cached_words = None


def test_check_no_hits():
    """Clean text should return no hits."""
    hits = check_sensitive_words("今天天气真好，适合出去散步。")
    assert hits == []


def test_check_with_hits():
    """Text containing known sensitive words should return hits."""
    hits = check_sensitive_words("这段视频包含色情内容，不适合播放。")
    assert len(hits) > 0
    keywords = [h["keyword"] for h in hits]
    assert "色情" in keywords


def test_check_multiple_occurrences():
    """Same word appearing twice should have count=2."""
    hits = check_sensitive_words("赌博是不好的，远离赌博。")
    matching = [h for h in hits if h["keyword"] == "赌博"]
    assert len(matching) == 1
    assert matching[0]["count"] == 2
    assert len(matching[0]["positions"]) == 2


def test_validate_empty():
    """Empty text should return invalid."""
    result = validate_script_input("")
    assert result["valid"] is False
    assert len(result["errors"]) > 0


def test_validate_too_long():
    """Text exceeding limit should return invalid."""
    long_text = "a" * 100
    result = validate_script_input(long_text, max_chars=50)
    assert result["valid"] is False
    assert result["char_count"] == 100
    assert len(result["errors"]) > 0


def test_validate_ok():
    """Normal text should return valid."""
    result = validate_script_input("这是一段正常的脚本文案。")
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["char_count"] > 0


def test_reload_blocklist():
    """Reload should return a positive count of loaded words."""
    count = reload_blocklist()
    assert count > 0
