from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Freshness(StrictModel):
    max_age_seconds: int = Field(300, ge=0, le=604800)
    unknown_age: Literal["refresh", "reject"] = "refresh"
    force_refresh: bool = False


class SearchRequest(StrictModel):
    workspace_id: str = Field("demo", min_length=1, max_length=80)
    run_id: str = Field(min_length=1, max_length=80)
    agent_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=160)
    freshness: Freshness = Field(default_factory=Freshness)
    deadline_seconds: float = Field(30, gt=0, le=180)
    params: dict[str, Any]

    @model_validator(mode="after")
    def validate_params(self):
        forbidden = {"api_key", "async", "output", "no_cache", "url"}
        if forbidden.intersection(self.params):
            raise ValueError("Transport and authentication parameters are gateway-controlled")
        if self.params.get("engine") not in {"google_light", "google", "google_news"}:
            raise ValueError("MVP engines: google_light, google, google_news")
        q = self.params.get("q")
        if not isinstance(q, str) or not 1 <= len(q) <= 2000:
            raise ValueError("A nonempty query of at most 2000 characters is required")
        if len(self.params) > 40:
            raise ValueError("Too many retrieval parameters")
        return self


class RunCreate(StrictModel):
    workspace_id: str = Field("demo", min_length=1, max_length=80)
    title: str = Field("Untitled investigation", min_length=1, max_length=200)
    budget_limit: int = Field(20, ge=0, le=1000)


class FindingCreate(StrictModel):
    run_id: str
    text: str = Field(min_length=1, max_length=5000)
    response_ids: list[str] = Field(min_length=1, max_length=30)


class MeshFailure(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

