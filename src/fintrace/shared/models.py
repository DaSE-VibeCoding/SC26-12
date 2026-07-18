"""Stable data contracts shared by pipelines and future front-end APIs."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_code: str = Field(pattern=r"^\d{6}$")
    company_name: str
    company_full_name: str | None = None
    exchange: str
    industry_code: str | None = None
    industry_name: str | None = None
    listing_date: date | None = None
    listing_status: str | None = None
    registered_address: str | None = None
    office_address: str | None = None
    secretary: str | None = None
    secretary_tel: str | None = None
    secretary_email: str | None = None
    website: str | None = None
    main_business: str | None = None
    company_info_year_requested: int
    company_info_year_used: int
    company_info_fallback: bool
    fallback_reason: str | None = None
