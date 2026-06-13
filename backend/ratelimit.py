"""Tiny in-memory sliding-window rate limiter for the login endpoint.

Single-process / single-container only (state is per-process, lost on
restart). That matches the current deployment (one app container); if
the app is ever scaled horizontally this must move to a shared store.

The check-and-record step is atomic under a lock, so a burst of N
concurrent requests can never exceed the limit — which is exactly what
defeats parallel brute-force (the old async sleep did not).
"""

import threading


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float) -> bool:
        """Record an attempt and return True, or False if over the limit."""
        cutoff = now - self.window
        with self._lock:
            recent = [t for t in self._events.get(key, ()) if t > cutoff]
            if len(recent) >= self.max_events:
                self._events[key] = recent
                return False
            recent.append(now)
            self._events[key] = recent
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


# Per-IP: 5 attempts per 5 minutes. Global backstop: 20 per minute across
# all IPs (covers distributed attempts; legit two-user traffic never hits it).
login_ip_limiter = SlidingWindowLimiter(max_events=5, window_seconds=300)
login_global_limiter = SlidingWindowLimiter(max_events=20, window_seconds=60)
