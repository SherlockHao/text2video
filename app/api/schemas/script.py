from pydantic import BaseModel


class SensitiveCheckRequest(BaseModel):
    text: str


class SensitiveWordHitItem(BaseModel):
    keyword: str
    count: int
    positions: list[int]
    context: str


class SensitiveCheckResponse(BaseModel):
    has_hits: bool
    hit_count: int
    hits: list[SensitiveWordHitItem]
    is_blocked: bool


class ScriptValidationRequest(BaseModel):
    text: str


class ScriptValidationResponse(BaseModel):
    valid: bool
    char_count: int
    errors: list[str]
