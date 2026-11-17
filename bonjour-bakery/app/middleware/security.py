import time
from collections import defaultdict, deque
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import get_settings


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "geolocation=(self), camera=(self), microphone=()")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
            h.setdefault("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                         "font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                         "base-uri 'self'; form-action 'self'")
        if get_settings().is_production:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        return resp


class RateLimiter:
    """In-process sliding-window limiter (per worker). Use a shared store if you scale horizontally."""
    def __init__(self):
        self.hits = defaultdict(deque)

    def check(self, key: str, limit: int, window: int) -> bool:
        now = time.time()
        q = self.hits[key]
        while q and q[0] < now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self):
        self.hits.clear()


limiter = RateLimiter()
