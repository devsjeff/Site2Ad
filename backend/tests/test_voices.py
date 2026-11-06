"""Languages, voices (Microsoft and ElevenLabs), sound effects and the translated voiceover."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import types

import httpx
import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.main import create_app
from app.studio import ai as studio_ai
from app.studio import assumptions as assumption_rules
from app.studio import translate
from app.studio.config import StageError
from app.studio.pipeline import validate_request
from app.video import eleven, sfx, voice
from app.video.base import VideoError, ffmpeg_path

from .conftest import make_settings
from .test_studio import FakeWriter

# ---------------------------------------------------------------------------------------------- the catalog


def test_every_language_has_voices_and_every_voice_is_complete():
    for language in catalog.LANGUAGES:
        assert catalog.voices_for(language, eleven=False), f"no free voice for {language}"
    for key, info in catalog.VOICES.items():
        assert info["engine"] in {"edge", "eleven"} and info["languages"] and set(info["languages"]) <= set(catalog.LANGUAGES), key
        if key not in {"auto", "none"}:
            assert info["gender"] in {"f", "m"}
            assert (info["voice"] if info["engine"] == "edge" else info["eleven_id"]), key
    assert {"neerja", "prabhat", "swara", "madhur", "ava", "andrew"} <= set(catalog.VOICES)  # the ids the ads and playbooks already use


def test_a_voice_that_cannot_be_used_is_replaced_by_one_of_the_same_language_and_gender():
    assert catalog.fallback_voice("el_sarah", "hi") == "swara" and catalog.fallback_voice("el_adam", "te") == "mohan"
    assert catalog.fallback_voice("neerja", "en") == "neerja" and catalog.fallback_voice("swara", "en") in {"neerja", "ava", "sonia"}
    assert catalog.default_voice("ta", "m") == "valluvar" and catalog.default_voice("xx") == "neerja"
    assert catalog.voices_for("hi")[-1].startswith("el_") and catalog.voices_for("te") == ["shruti", "mohan"]  # free voices come first; Telugu has no ElevenLabs voice


# ---------------------------------------------------------------------------------------------- ElevenLabs


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_elevenlabs_speaks_caches_and_never_pays_twice(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        assert request.headers["xi-api-key"] == "k" and re.search(r"/text-to-speech/(VOICE|OTHER)\?", str(request.url))
        return httpx.Response(200, content=b"ID3fakeaudio")

    engine = eleven.ElevenLabs("k", "eleven_multilingual_v2", tmp_path / "cache")

    async def go():
        async with mock_client(handler) as client:
            await engine.speak("Silent screens", "VOICE", tmp_path / "a.mp3", client=client)
            await engine.speak("Silent screens", "VOICE", tmp_path / "b.mp3", client=client)  # same line: from the cache
            await engine.speak("Silent screens", "OTHER", tmp_path / "c.mp3", client=client)  # another voice: a new request

    asyncio.run(go())
    assert len(calls) == 2 and calls[0]["model_id"] == "eleven_multilingual_v2" and (tmp_path / "b.mp3").read_bytes() == b"ID3fakeaudio"
    assert engine.characters == 2 * len("Silent screens")


def test_a_rejected_key_or_a_used_up_plan_switches_the_engine_off_for_good(tmp_path):
    for status, body, reason in ((401, "{}", "rejected the API key"), (402, "{}", "no characters left"), (400, '{"detail": {"status": "quota_exceeded"}}', "no characters left")):
        engine = eleven.ElevenLabs("k", cache_dir=None)

        async def go():
            async with mock_client(lambda request: httpx.Response(status, text=body)) as client:
                with pytest.raises(eleven.ElevenUnavailable, match=reason):
                    await engine.speak("Hello", "V", tmp_path / "x.mp3", client=client)
                assert not engine.enabled
                with pytest.raises(eleven.ElevenUnavailable):  # and it does not ask again
                    await engine.speak("Hello again", "V", tmp_path / "x.mp3", client=client)

        asyncio.run(go())


def test_a_busy_answer_is_retried_and_two_requests_run_at_a_time(tmp_path, monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(eleven.asyncio, "sleep", lambda seconds: real_sleep(0))  # the retry waits are skipped
    state = {"busy": 1, "running": 0, "peak": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["running"] += 1
        state["peak"] = max(state["peak"], state["running"])
        await asyncio.sleep(0.01)
        state["running"] -= 1
        if state["busy"] > 0:
            state["busy"] -= 1
            return httpx.Response(429, text="too many concurrent requests")
        return httpx.Response(200, content=b"audio")

    engine = eleven.ElevenLabs("k", cache_dir=None)

    async def go():
        async with mock_client(handler) as client:
            await asyncio.gather(*(engine.speak(f"line {i}", "V", tmp_path / f"{i}.mp3", client=client) for i in range(6)))

    asyncio.run(go())
    assert state["peak"] <= eleven.CONCURRENT and all((tmp_path / f"{i}.mp3").is_file() for i in range(6))


def test_an_elevenlabs_voice_falls_back_to_a_microsoft_voice_of_the_same_language(tmp_path, monkeypatch):
    spoken = []

    class Capture:
        def __init__(self, text, voice_name, rate="+0%", pitch="+0Hz"):
            spoken.append(voice_name)

        async def save(self, path):
            open(path, "wb").write(b"mp3")

    monkeypatch.setattr("edge_tts.Communicate", Capture)
    monkeypatch.setattr(voice, "_eleven", None)  # no ElevenLabs key
    out = tmp_path / "x.mp3"
    assert asyncio.run(voice.synthesize("नमस्ते", "el_sarah", out, language="hi")) == "edge" and spoken == ["hi-IN-SwaraNeural"]  # the free Hindi woman's voice
    spoken.clear()
    assert asyncio.run(voice.synthesize("Hello", "madhur", out)) == "edge" and spoken == ["hi-IN-MadhurNeural"]


# ---------------------------------------------------------------------------------------------- sound effects


def test_every_sound_effect_is_made_and_audible(tmp_path):
    made = sfx.library(tmp_path)
    assert set(made) == set(sfx.RECIPES)
    for name, path in made.items():
        result = subprocess.run([ffmpeg_path(), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        peak = float(re.search(r"max_volume: (-?[\d.]+) dB", result.stderr).group(1))
        assert -6.0 < peak <= 0.0, (name, peak)  # all at the same, healthy level


def test_the_effects_follow_the_storyboard():
    shots = [
        {"seconds": 4.0, "transition": "slide", "visual": {"type": "screenshot", "id": "01"}, "caption": "Live map"},
        {"seconds": 4.0, "transition": "zoom", "visual": {"type": "graphic", "template": "price", "props": {"price": "₹4,000"}}, "caption": ""},
        {"seconds": 3.5, "transition": "cut", "visual": {"type": "graphic", "template": "cta", "props": {}}, "caption": ""},
    ]
    effects = sfx.effects_for_board(shots)
    names = [(round(e.time, 2), e.name) for e in effects]
    assert names[0] == (0.0, "impact") and (3.92, "whoosh") in names  # a slide into shot 2 is heard just before it
    assert any(n == "ding" and 4.2 < t < 4.6 for t, n in names)  # the price stamps in with a ding
    assert (8.0, "impact") in names  # the zoom into shot 3
    assert any(n == "chime" and 8.5 < t < 9.5 for t, n in names) and all(e.time < 11.5 for e in effects)
    assert effects == sorted(effects, key=lambda e: e.time) and all(0 < e.gain <= 1 for e in effects)


def test_the_effects_are_mixed_into_the_video(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=3", "-pix_fmt", "yuv420p", str(video)], check=True)
    effects = [sfx.Effect(0.2, "pop", 0.8), sfx.Effect(1.0, "whoosh", 0.7), sfx.Effect(2.0, "ding", 0.6)]
    result = asyncio.run(voice.add_sound(video, tmp_path / "work", voice_id="none", music_id="none", cues=[], effects=effects))
    assert result.effects_used == 3 and not result.voice_used
    probe = subprocess.run([ffmpeg_path(), "-i", str(video), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    assert float(re.search(r"max_volume: (-?[\d.]+) dB", probe.stderr).group(1)) > -20.0  # something can be heard


# ---------------------------------------------------------------------------------------------- the translated voiceover

WANTED = [{"n": 1, "english": "Media is ₹4,000 per cab per month", "max_words": 12}, {"n": 2, "english": "Live GPS on every play", "max_words": 9}]


def test_a_translation_must_keep_every_figure_and_fit_its_shot():
    good = {"lines": [{"n": 1, "text": "मीडिया 4,000 रुपये प्रति कैब प्रति माह"}, {"n": 2, "text": "हर प्ले पर लाइव जीपीएस"}]}
    assert translate.validate_translation(good, WANTED) == []
    lost = {"lines": [{"n": 1, "text": "मीडिया प्रति कैब प्रति माह"}, {"n": 2, "text": "हर प्ले पर लाइव जीपीएस"}]}
    assert any("lost the figure" in p for p in translate.validate_translation(lost, WANTED))
    invented = {"lines": [{"n": 1, "text": "मीडिया 4,000 रुपये प्रति कैब"}, {"n": 2, "text": "हर प्ले पर 99 लाइव जीपीएस"}]}
    assert any("line 2" in p and "does not have" in p for p in translate.validate_translation(invented, WANTED))
    long = {"lines": [{"n": 1, "text": "मीडिया 4,000 रुपये " + "शब्द " * 20}, {"n": 2, "text": "ठीक"}]}
    assert any("line 1" in p and "shorter" in p for p in translate.validate_translation(long, WANTED))
    assert any("missing" in p for p in translate.validate_translation({"lines": [{"n": 1, "text": "मीडिया 4,000"}]}, WANTED))


def board():
    return {"shots": [{"n": 1, "seconds": 4.0, "voice": "Media is ₹4,000 per cab per month"}, {"n": 2, "seconds": 4.0, "voice": ""}, {"n": 3, "seconds": 4.0, "voice": "Live GPS on every play"}]}


def test_only_new_or_changed_lines_are_translated_and_a_failure_falls_back_to_english(monkeypatch):
    asked = []

    def fake(wanted, language):
        asked.append([w["n"] for w in wanted])
        return {w["n"]: f"[{language}] {w['english']}" for w in wanted}

    monkeypatch.setattr(translate, "translate_lines", fake)
    shots = board()
    assert translate.ensure_translations(shots, "hi") == "" and asked == [[1, 3]]
    assert shots["shots"][0]["voice_local"].startswith("[hi]") and "voice_local" not in shots["shots"][1]
    assert translate.ensure_translations(shots, "hi") == "" and asked == [[1, 3]]  # nothing changed: no request
    shots["shots"][2]["voice"] = "Live GPS map of every play"  # the check stage reworded one shot
    translate.ensure_translations(shots, "hi")
    assert asked == [[1, 3], [3]] and translate.ensure_translations(shots, "en") == ""

    def broken(wanted, language):
        raise StageError("The AI writer's free daily limit is used up.")

    monkeypatch.setattr(translate, "translate_lines", broken)
    fresh = board()
    note = translate.ensure_translations(fresh, "ta")
    assert "could not be translated to Tamil" in note and "spoken in English" in note and all("voice_local" not in s for s in fresh["shots"])


def test_translate_asks_the_ai_writer_and_checks_the_answer():
    answers = [json.dumps({"lines": [{"n": 1, "text": "कोई आंकड़ा नहीं"}, {"n": 2, "text": "लाइव जीपीएस"}]}),
               json.dumps({"lines": [{"n": 1, "text": "मीडिया 4,000 रुपये प्रति कैब प्रति माह"}, {"n": 2, "text": "लाइव जीपीएस"}]})]
    writer = FakeWriter(*answers)
    studio_ai.set_client(writer)
    try:
        lines = translate.translate_lines(WANTED, "hi")
    finally:
        studio_ai.set_client(None)
    assert writer.calls == 2 and lines[1].startswith("मीडिया 4,000")  # the first answer lost the figure and was sent back


# ---------------------------------------------------------------------------------------------- assumptions and the request


def test_a_voice_must_speak_the_language_of_the_video():
    base = {"video_type": "promo", "music": "calm", "cta": {"text": "Go", "target": "x"}, "must_include": []}
    notes = {"claims": [{"id": "C1"}]}
    assert assumption_rules.validate_edited({**base, "voice": "swara", "language": "hi"}, notes) == []
    assert assumption_rules.validate_edited({**base, "voice": "el_adam", "language": "hi"}, notes) == []  # ElevenLabs speaks Hindi
    assert any("does not speak Hindi" in p for p in assumption_rules.validate_edited({**base, "voice": "neerja", "language": "hi"}, notes))
    assert any("does not speak Telugu" in p for p in assumption_rules.validate_edited({**base, "voice": "el_adam", "language": "te"}, notes))
    assert any("language" in p for p in assumption_rules.validate_edited({**base, "voice": "neerja", "language": "klingon"}, notes))
    assert assumption_rules.validate_edited({**base, "voice": "none", "language": "te"}, notes) == []


def test_the_request_checks_language_and_voice_together():
    ok = {"video_type": "promo", "length": 20}
    validate_request({**ok, "language": "hi", "voice": "madhur"})
    validate_request({**ok, "language": "ta", "voice": "auto"})
    with pytest.raises(StageError, match="does not speak Hindi"):
        validate_request({**ok, "language": "hi", "voice": "neerja"})
    with pytest.raises(StageError, match="language must be one of"):
        validate_request({**ok, "language": "xx"})


@pytest.fixture
def client(tmp_path):
    settings = make_settings(tmp_path, ai_prompt_api_key="test-key", elevenlabs_api_key="el-test-key", rate_limit_per_minute=1000)
    with TestClient(create_app(settings)) as http:
        yield http


def test_the_config_lists_languages_and_only_offers_elevenlabs_voices_while_the_key_works(client):
    config = client.get("/api/config").json()
    assert {l["id"] for l in config["languages"]} == set(catalog.LANGUAGES) and config["eleven_available"] is True
    voices = {v["id"]: v for v in config["voices"]}
    assert voices["el_adam"]["engine"] == "eleven" and "hi" in voices["el_adam"]["languages"] and voices["swara"]["languages"] == ["hi"]
    voice._eleven.off_reason = "the ElevenLabs plan has no characters left"  # the plan runs out while the server runs
    config = client.get("/api/config").json()
    assert config["eleven_available"] is False and not any(v["engine"] == "eleven" for v in config["voices"])


def test_the_studio_request_takes_language_voice_and_sound_effects(client):
    body = {"url": "https://a.example", "video_type": "promo", "length": 20, "platform": "16:9"}
    assert client.post("/api/studio/jobs", json={**body, "language": "klingon"}).status_code == 422
    assert client.post("/api/studio/jobs", json={**body, "voice": "robot"}).status_code == 422
    assert client.post("/api/studio/jobs", json={**body, "voice": "none"}).status_code == 422  # "no voice" is chosen on the review screen
    mismatch = client.post("/api/studio/jobs", json={**body, "language": "hi", "voice": "neerja"})
    assert mismatch.status_code == 422 and "does not speak Hindi" in mismatch.json()["detail"]


# ---------------------------------------------------------------------------------------------- the whole assumptions stage


def assumptions_run(tmp_path, **request):
    from app.studio.config import Run

    from .test_studio import BOARD_CAPTURE, NOTES

    run = Run(tmp_path / "run")
    Run.write_json(run.request_json, {"url": "https://x.example", "video_type": "promo", "length": 20, "platform": "16:9", "claims": [], **request})
    Run.write_json(run.product_json, {**NOTES, "what_it_is": "Silent cab screens.", "who_for": "Advertisers."})
    Run.write_json(run.brand_json, {"tone": "Direct", "tone_words": ["direct"], "fonts": {"heading": "Outfit", "body": "Inter"}})
    Run.write_json(run.capture_json, {**BOARD_CAPTURE, "blocks": []})
    return run


def writer_says(voice_id):
    return json.dumps({"audience": "Brand marketers", "key_message": "Reach riders in cabs", "tone": "Direct", "voice": voice_id, "voice_reason": "fits the brand", "music": "calm",
                       "music_reason": "steady", "cta_text": "Launch", "cta_target": "x.example", "must_include": [{"what": "the price", "claims": ["C2"]}], "must_avoid": ["other companies"]})


def test_the_assumptions_stage_honours_the_language_and_the_voice_chosen_on_the_form(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "_eleven", eleven.ElevenLabs("k"))  # ElevenLabs works
    cases = (
        ({"language": "hi", "voice": "auto"}, "el_sarah", "el_sarah"),  # the AI picks a voice that speaks Hindi
        ({"language": "hi", "voice": "madhur"}, "swara", "madhur"),  # the form's choice wins over the AI's
        ({"language": "te", "voice": "auto"}, "neerja", "shruti"),  # the AI picked a voice that does not speak Telugu: fixed in code, no retry
        ({"language": "en", "voice": "auto"}, "nonsense", "el_adam"),  # an unknown id: the best available voice
    )
    for request, ai_voice, expected in cases:
        writer = FakeWriter(writer_says(ai_voice))
        studio_ai.set_client(writer)
        try:
            result = assumption_rules.build_assumptions(assumptions_run(tmp_path / request["language"] / request["voice"], **request), "promo")
        finally:
            studio_ai.set_client(None)
        assert result["voice"] == expected and result["language"] == request["language"] and result["sound_effects"] is True, (request, result["voice"])
        assert writer.calls == 1  # a wrong voice never costs a retry
    studio_ai.set_client(FakeWriter(writer_says("shruti")))
    try:
        result = assumption_rules.build_assumptions(assumptions_run(tmp_path / "fx", language="te", sound_effects=False), "promo")
    finally:
        studio_ai.set_client(None)
    assert result["sound_effects"] is False and result["voice"] == "shruti"


def test_elevenlabs_voices_are_not_offered_to_the_ai_when_the_engine_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "_eleven", None)
    seen = []

    class Recording(FakeWriter):
        async def complete(self, system, user, max_tokens=1400, *, model="", timeout=0.0, reasoning=None):
            seen.append(system)
            return await super().complete(system, user, max_tokens, model=model, timeout=timeout, reasoning=reasoning)

    studio_ai.set_client(Recording(writer_says("swara")))
    try:
        result = assumption_rules.build_assumptions(assumptions_run(tmp_path, language="hi"), "promo")
    finally:
        studio_ai.set_client(None)
    assert "el_adam" not in seen[0] and "swara" in seen[0] and "Hindi" in seen[0] and result["voice"] == "swara"
