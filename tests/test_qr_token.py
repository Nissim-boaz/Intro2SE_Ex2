import time
from modules.sessions.service import SessionsService

def test_qr_token_changes_every_6_seconds(app):
    with app.app_context():
        session_id = "test-session-123"
        # Window size is 6 seconds
        t0 = 600.0  # window = 600 // 6 = 100
        t1 = 605.9  # window = 605.9 // 6 = 100 (same window)
        t2 = 606.1  # window = 606.1 // 6 = 101 (new window)

        token0 = SessionsService.generate_qr_token(session_id, t0)
        token1 = SessionsService.generate_qr_token(session_id, t1)
        token2 = SessionsService.generate_qr_token(session_id, t2)

        # Tokens within the same 6-second window are identical
        assert token0 == token1

        # Tokens in different 6-second windows are different
        assert token0 != token2

def test_qr_token_from_previous_window_is_rejected(app):
    with app.app_context():
        session_id = "test-session-456"
        t_prev = 600.0
        t_curr = 606.5

        prev_token = SessionsService.generate_qr_token(session_id, t_prev)
        curr_token = SessionsService.generate_qr_token(session_id, t_curr)

        # Token from previous window must be rejected at current window
        assert SessionsService.verify_qr_token(session_id, prev_token, ts=t_curr) is False

        # Current token is valid at current window
        assert SessionsService.verify_qr_token(session_id, curr_token, ts=t_curr) is True
