import threading
import time
import uuid
from datetime import datetime, timezone
import httpx


class ProviderError(Exception):
    def __init__(self, code, message, retryable=False, retry_after=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.retryable, self.retry_after = retryable, retry_after


class FixtureProvider:
    mode = "fixture"
    def __init__(self, delay=0.45):
        self.delay, self.calls, self.revision = delay, 0, 1
        self._lock = threading.Lock()
        self._per_query = {}

    def search(self, params, refresh=False):
        with self._lock:
            self.calls += 1
            q = params["q"]
            self._per_query[q] = self._per_query.get(q, 0) + 1
            count, revision = self._per_query[q], self.revision
        time.sleep(self.delay)
        if "[retry-once]" in q and count == 1:
            raise ProviderError("PROVIDER_RATE_LIMIT", "Synthetic rate limit", True, 0.03)
        if "[auth-fail]" in q:
            raise ProviderError("PROVIDER_AUTH_ERROR", "Synthetic authentication failure")
        stamp = datetime.now(timezone.utc).isoformat()
        if "[stale]" in q and not refresh:
            stamp = datetime.fromtimestamp(time.time()-7200, timezone.utc).isoformat()
        metadata = {"id": "fixture-"+uuid.uuid4().hex[:10], "status": "Success", "created_at": stamp}
        if "[unknown-age]" in q:
            metadata.pop("created_at")
        free = "free-threaded" in q
        if "[empty]" in q:
            results = []
        else:
            results = [
                {"position": 1, "title": "Synthetic compatibility bulletin" if not free else "Synthetic free-threaded support bulletin",
                 "link": "https://example.org/fixture/compatibility",
                 "snippet": ("Fixture only. Standard interpreter support is documented; free-threaded support requires separate evidence."
                             if revision % 2 == 1 else "Fixture only. Revised bulletin: platform qualification now requires review.")},
                {"position": 2, "title": "Synthetic platform notes", "link": "https://example.org/fixture/platform",
                 "snippet": "Fixture only. Confirm exact version and platform before drawing a conclusion."},
            ]
        key = "news_results" if params["engine"] == "google_news" else "organic_results"
        return {"search_metadata": metadata, "search_parameters": params, key: results}


class SerpApiProvider:
    mode = "live"
    def __init__(self, api_key, timeout=30):
        if not api_key:
            raise ValueError("Live mode requires SERPAPI_API_KEY on the gateway")
        self.api_key, self.timeout = api_key, timeout

    def search(self, params, refresh=False):
        request = {**params, "api_key": self.api_key, "output": "json"}
        if refresh:
            request["no_cache"] = "true"
        try:
            response = httpx.get("https://serpapi.com/search.json", params=request, timeout=self.timeout)
        except (httpx.TimeoutException, httpx.NetworkError):
            raise ProviderError("PROVIDER_ERROR", "Provider network failure; execution may be ambiguous", True) from None
        if response.status_code in (401,403):
            raise ProviderError("PROVIDER_AUTH_ERROR", "Provider rejected authentication")
        if response.status_code == 429 or response.status_code >= 500:
            try:
                after = float(response.headers.get("Retry-After", "0")) or None
            except ValueError:
                after = None
            raise ProviderError("PROVIDER_RATE_LIMIT" if response.status_code==429 else "PROVIDER_ERROR", "Transient provider error", True, after)
        if response.status_code >= 400:
            raise ProviderError("PROVIDER_ERROR", "Provider rejected the search parameters")
        if len(response.content) > 5_000_000:
            raise ProviderError("PROVIDER_ERROR", "Provider response exceeds 5 MB limit")
        try:
            raw = response.json()
        except ValueError:
            raise ProviderError("PROVIDER_ERROR", "Provider returned invalid JSON") from None
        if not isinstance(raw, dict) or raw.get("error") or raw.get("search_metadata",{}).get("status") == "Error":
            # Never expose upstream error text, which can contain sensitive request details.
            raise ProviderError("PROVIDER_ERROR", "Provider reported a search failure")
        # Redact echoed credentials, including those embedded in pagination URLs.
        def sanitize(value):
            if isinstance(value,dict):
                return {k:sanitize(v) for k,v in value.items() if k.lower() not in {"api_key","authorization"}}
            if isinstance(value,list): return [sanitize(v) for v in value]
            if isinstance(value,str): return value.replace(self.api_key,"[REDACTED]")
            return value
        return sanitize(raw)

