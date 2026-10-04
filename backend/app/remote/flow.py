"""Flow control for remote input: rate limits and staleness without trusting device clocks.

Device clocks are not synchronized with Core. ``ClockEstimator`` learns the
offset between a session's clock and Core's from the messages themselves: for
every message, ``received - sent`` = offset + network delay. The smallest value
over a window is the best estimate of the offset (the least-delayed message),
so the *age* of a message is how much more delayed it was than that. A burst
released after a Wi-Fi stall therefore shows a large age and can be dropped,
while a constant clock difference costs nothing.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

WINDOW = 64
REBASELINE_AFTER = 16


@dataclass
class ClockEstimator:
    samples: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    baseline: Optional[float] = None
    consecutive_late: int = 0
    rebaselined: int = 0

    def observe(self, sent_ms: float, received_ms: float) -> float:
        """Record a message and return its age in milliseconds (>= 0)."""
        sample = received_ms - sent_ms
        self.samples.append(sample)
        if self.baseline is None or sample < self.baseline:
            self.baseline = sample
            self.consecutive_late = 0
            return 0.0
        return sample - self.baseline

    def late(self, age_ms: float, max_age_ms: float) -> bool:
        """True when a message is too old. A sustained shift (clock jump after sleep,
        not a burst) re-baselines on the recent samples instead of rejecting forever."""
        if age_ms <= max_age_ms:
            self.consecutive_late = 0
            return False
        self.consecutive_late += 1
        if self.consecutive_late >= REBASELINE_AFTER:
            recent = list(self.samples)[-REBASELINE_AFTER:]
            self.baseline = min(recent)
            self.consecutive_late = 0
            self.rebaselined += 1
        return True

    def reset(self) -> None:
        self.samples.clear()
        self.baseline = None
        self.consecutive_late = 0

    def public(self) -> dict:
        return {"offset_ms": None if self.baseline is None else round(self.baseline, 1), "rebaselined": self.rebaselined}


@dataclass
class TokenBucket:
    rate: float
    burst: float
    tokens: float = -1.0
    updated: float = 0.0

    def allow(self, now: float, cost: float = 1.0) -> bool:
        if self.tokens < 0:
            self.tokens = self.burst
            self.updated = now
        self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


# Per-session budgets by message class (messages per second, burst).
RATE_CLASSES = {
    "reliable": (20.0, 40.0),
    "realtime": (90.0, 120.0),
    "voice": (1.0, 3.0),
    "approval": (5.0, 10.0),
    "control": (2.0, 6.0),
}
