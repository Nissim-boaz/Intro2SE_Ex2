from modelplus.services.tokens import TokenClock


class FakeClock(TokenClock):
    """שעון שאפשר להזיז ידנית."""

    def __init__(self, start: float = 1_000_000.0, window_seconds: int = 6):
        super().__init__(window_seconds)
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds
