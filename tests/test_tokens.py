from modelplus.services.tokens import AudioTokenService, QrTokenService
from tests.fakes import FakeClock


def test_qr_token_changes_every_window():
    clock = FakeClock(start=600.0)  # תחילת חלון
    qr = QrTokenService("secret", clock)
    first = qr.token(7)
    clock.advance(5.9)
    assert qr.token(7) == first
    clock.advance(0.2)
    assert qr.token(7) != first


def test_qr_token_accepts_current_and_previous_only():
    clock = FakeClock(start=600.0)
    qr = QrTokenService("secret", clock)
    token = qr.token(7)
    assert qr.verify(7, token)
    clock.advance(6)  # חלון אחד אחרי
    assert qr.verify(7, token)
    clock.advance(6)  # שני חלונות אחרי: נדחה
    assert not qr.verify(7, token)


def test_qr_token_bound_to_sample_and_secret():
    clock = FakeClock()
    qr = QrTokenService("secret", clock)
    assert not qr.verify(8, qr.token(7))
    assert not QrTokenService("other", clock).verify(7, qr.token(7))
    assert not qr.verify(7, "")
    assert not qr.verify(7, None)


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


def test_audio_code_rotates_and_expires():
    clock = FakeClock(start=600.0)
    audio = AudioTokenService("secret", clock)
    code = audio.code(3)
    assert 0 <= code < 4096
    assert audio.verify(3, code)
    clock.advance(12)  # עדיין בתוך 3 חלונות
    assert audio.verify(3, code)
    clock.advance(6)
    assert not audio.verify(3, code)


def test_audio_rejects_garbage():
    audio = AudioTokenService("secret", FakeClock())
    assert not audio.verify(3, "abc")
    assert not audio.verify(3, None)


def test_audio_and_qr_are_independent():
    clock = FakeClock()
    a = AudioTokenService("secret", clock)
    q = QrTokenService("secret", clock)
    # שני ה-purposes שונים, כך שאי אפשר לגזור אחד מהשני
    assert a._digest(1, 5) != q._digest(1, 5)
