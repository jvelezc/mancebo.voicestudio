import sys
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from services import translation_engines as subject


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    calls = []

    class Tokenizer:
        def __init__(self):
            self.stanza_pipeline = None
            self.stanza_lang_code = "en"
            self.pkg = SimpleNamespace(package_path=tmp_path)

    tokenizer = Tokenizer()
    leaf = SimpleNamespace(sentencizer=tokenizer)
    wrapped = SimpleNamespace(underlying=leaf, translate=lambda text: "es: " + text)
    parent = ModuleType("argostranslate")
    translator = ModuleType("argostranslate.translate")
    translator.translate = lambda *args: calls.append(("legacy", args)) or "legacy result"
    translator.get_translation_from_codes = lambda *args: wrapped
    sbd = ModuleType("argostranslate.sbd")
    sbd.StanzaSentencizer = Tokenizer
    stanza = ModuleType("stanza")
    stanza.Pipeline = lambda **kwargs: calls.append(("pipeline", kwargs)) or object()
    for name, module in (("argostranslate", parent), ("argostranslate.translate", translator),
                         ("argostranslate.sbd", sbd), ("stanza", stanza)):
        monkeypatch.setitem(sys.modules, name, module)
    return calls, tokenizer, wrapped


def test_managed_translation_uses_installed_resources_without_download_or_global_patch(monkeypatch, runtime):
    calls, tokenizer, wrapped = runtime
    monkeypatch.setenv("VOICESTUDIO_ARGOS_OFFLINE", "1")
    assert subject.translate_argos("Complete first sentence.", "en", "es") == "es: Complete first sentence."
    assert subject.translate_argos("Complete last sentence.", "en", "es") == "es: Complete last sentence."
    assert len(calls) == 1
    _, options = calls[0]
    assert options["download_method"] is None
    assert options["use_gpu"] is False
    assert options["dir"] == str(tokenizer.pkg.package_path / "stanza")
    assert tokenizer.stanza_pipeline is not None


def test_standalone_translation_keeps_existing_runtime_behavior(monkeypatch, runtime):
    calls, tokenizer, _ = runtime
    monkeypatch.delenv("VOICESTUDIO_ARGOS_OFFLINE", raising=False)
    assert subject.translate_argos("Hello", "en", "es") == "legacy result"
    assert calls == [("legacy", ("Hello", "en", "es"))]
    assert tokenizer.stanza_pipeline is None


def test_missing_installed_tokenizer_fails_without_untranslated_success(monkeypatch, runtime):
    calls, _, wrapped = runtime
    monkeypatch.setenv("VOICESTUDIO_ARGOS_OFFLINE", "1")
    wrapped.underlying.sentencizer = object()
    with pytest.raises(RuntimeError, match="not qualified"):
        subject.translate_argos("Must not silently pass through", "en", "es")
    assert calls == []


def test_managed_translation_does_not_log_scripts_but_retains_warnings(monkeypatch, runtime, caplog):
    _, _, wrapped = runtime
    monkeypatch.setenv("VOICESTUDIO_ARGOS_OFFLINE", "1")
    log = logging.getLogger("argostranslate.utils")
    monkeypatch.setattr(log, "level", logging.INFO)

    def translate(text):
        log.info("Source sentence: %s", text)
        log.info("Translated sentence: confidential translation")
        log.warning("Installed translation needs review")
        return "translated result"

    wrapped.translate = translate
    with caplog.at_level(logging.INFO):
        assert subject.translate_argos("confidential source", "en", "es") == "translated result"
    assert "confidential" not in caplog.text
    assert "Installed translation needs review" in caplog.text


def test_standalone_translation_does_not_change_library_logging(monkeypatch, runtime):
    monkeypatch.delenv("VOICESTUDIO_ARGOS_OFFLINE", raising=False)
    log = logging.getLogger("argostranslate.utils")
    monkeypatch.setattr(log, "level", logging.INFO)
    assert subject.translate_argos("Hello", "en", "es") == "legacy result"
    assert log.level == logging.INFO
