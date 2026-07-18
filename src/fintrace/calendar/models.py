from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    company_code: str = Field(pattern=r"^\d{6}$")
    company_name: str
    report_period: date
    report_type: str
    event_type: str
    event_date: date
    event_time: time | None = None
    previous_date: date | None = None
    announcement_title: str | None = None
    source_site: str
    source_url: str | None = None
    query_keyword: str | None = None
    queried_at: datetime | None = None
    manual_review_required: bool = False

    @field_validator("event_time", mode="before")
    @classmethod
    def empty_time_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("previous_date", mode="before")
    @classmethod
    def empty_previous_date_is_none(cls, value: object) -> object:
        return None if value == "" else value
