"""
Regression test for app.services.audio.TTSService._get_model_path.

TTSService.generate_audio()/_generate_audio_sync() call
_get_model_path(request.voice, request.model), where request is an
AudioGenerateRequest - a BaseSchema field (use_enum_values=True in
app/models/common.py), so request.voice/request.model are plain strings,
not TTSVoice/TTSModel instances. _get_model_path() did `model.value` to
build the .onnx filename, which crashed with
AttributeError: 'str' object has no attribute 'value' on every single
TTS generation call. Confirmed live against a real Piper instance
(docker compose): POST /api/audio/tts/generate returned
{"detail": "Ошибка генерации TTS: 'str' object has no attribute 'value'"}
before this fix.

Same root cause as ROADMAP.md's Баг №1 (widespread use_enum_values=True
pattern) and its recurrence documented as Баг №7 for AudioService.
"""

from app.services.audio import TTSService
from app.models.audio import TTSVoice, TTSModel


def make_tts_service() -> TTSService:
    # _get_model_path() never touches db_pool/redis, so plain sentinels
    # are enough - no fakes/mocks needed for this unit.
    return TTSService(db_pool=None, redis_client=None)


def test_get_model_path_accepts_plain_strings_like_use_enum_values_does():
    service = make_tts_service()
    path = service._get_model_path("denis", "medium")
    assert path.name == "ru_RU-denis-medium.onnx"


def test_get_model_path_accepts_real_enum_instances():
    service = make_tts_service()
    path = service._get_model_path(TTSVoice.IRINA, TTSModel.SMALL)
    assert path.name == "ru_RU-irina-small.onnx"


def test_get_model_path_picks_correct_language_per_voice():
    service = make_tts_service()
    assert service._get_model_path("thorsten", "medium").name == "de_DE-thorsten-medium.onnx"
    assert service._get_model_path("alan", "medium").name == "en_US-alan-medium.onnx"
