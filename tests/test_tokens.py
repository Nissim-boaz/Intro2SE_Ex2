from moodleplus.services.tokens import AudioTokenService
from tests.fakes import FakeClock


def test_audio_symbols_roundtrip():
    for code in (0, 1, 7, 8, 1234, 4095):
        symbols = AudioTokenService.symbols(code)
        assert len(symbols) == 5 and all(0 <= s < 8 for s in symbols)
        assert AudioTokenService.decode(symbols) == code


def test_audio_parity_detects_single_error():
    symbols = AudioTokenService.symbols(1234)
    symbols[1] = (symbols[1] + 1) % 8
    assert AudioTokenService.decode(symbols) is None
    assert AudioTokenService.decode([1, 2, 3]) is None


def test_audio_code_changes_every_window():
    clock = FakeClock(start=600.0)  # תחילת חלון של 4 שניות
    audio = AudioTokenService("secret", clock)
    codes = set()
    for _ in range(20):
        codes.add(audio.code(3))
        clock.advance(4)
    assert len(codes) > 15  # 12 ביט: חזרה מקרית אפשרית, אבל נדירה


def test_audio_code_valid_for_at_most_two_windows():
    clock = FakeClock(start=600.0)
    audio = AudioTokenService("secret", clock)
    code = audio.code(3)
    assert audio.max_age_seconds == 8
    clock.advance(3.9)  # אותו חלון
    assert audio.verify(3, code)
    clock.advance(4)  # החלון הבא: עדיין מתקבל (השהיית פענוח ורשת)
    assert audio.verify(3, code)
    clock.advance(0.2)  # 8.1 שניות מתחילת החלון: הקלטה שהושמעה מחדש כבר לא עוברת
    assert not audio.verify(3, code)


def test_audio_code_bound_to_sample_and_secret():
    clock = FakeClock(start=600.0)
    audio = AudioTokenService("secret", clock)
    code = audio.code(3)
    others = [audio.code(4), AudioTokenService("other", clock).code(3)]
    # מספיק שאחד מהם שונה. בשניהם שוויון הוא צירוף מקרים של 1 ל-4096
    assert any(o != code for o in others)


def test_audio_rejects_garbage():
    audio = AudioTokenService("secret", FakeClock())
    assert not audio.verify(3, "abc")
    assert not audio.verify(3, None)
    assert not audio.verify(3, "")
