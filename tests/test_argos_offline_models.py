import sys
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
