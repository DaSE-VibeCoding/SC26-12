"""Structured errors exposed by FinTrace pipelines and command-line tools."""

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FinTraceError(Exception):
    message: str
    code: str = "fintrace_error"
    step: str | None = None
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.step:
            payload["step"] = self.step
        if self.details:
            payload["details"] = self.details
        return payload


class PathConfigError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="path_config_error", **kwargs)


class InputFileNotFoundError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="input_file_not_found", **kwargs)


class InvalidCompanyCodeError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="invalid_company_code", **kwargs)


class CompanyNotFoundError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="company_not_found", **kwargs)


class CompanyMasterDataUnavailableError(FinTraceError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, code="company_master_data_unavailable", **kwargs)
