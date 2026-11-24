import re
from pydantic import BaseModel, Field, field_validator

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
GEO_SPLIT_RE = re.compile(r"[\s,;]+")
MAX_COUNTRIES = 50


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: list[str] = Field(description="ISO 3166-1 alpha-2 country codes: a string like \"MX, AU, RO\" or a list")
    offer_id: int = Field(gt=0)
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Campaign name cannot be empty")
        return v

    @field_validator("geo", mode="before")
    @classmethod
    def parse_geo(cls, v):
        parts = GEO_SPLIT_RE.split(v) if isinstance(v, str) else list(v or [])
        codes: list[str] = []
        for part in parts:
            code = str(part).strip().upper()
            if not code:
                continue
            if not COUNTRY_RE.match(code):
                raise ValueError(f"\"{part}\" is not a country code: use two-letter codes like MX, AU, RO")
            if code not in codes:
                codes.append(code)
        if not codes:
            raise ValueError("Enter at least one country, e.g. DE or MX, AU, RO")
        if len(codes) > MAX_COUNTRIES:
            raise ValueError(f"Too many countries: {MAX_COUNTRIES} max")
        return codes


class CampaignCreateOut(BaseModel):
    id: int
    name: str
    alias: str | None
    geo: list[str]
    offer_id: int
    geo_stream_id: int
    offer_stream_id: int
    admin_url: str


class OfferPatchIn(BaseModel):
    share: int | None = Field(default=None, ge=0, le=100)
    pinned: bool | None = None


class AddOfferIn(BaseModel):
    offer_id: int = Field(gt=0)
