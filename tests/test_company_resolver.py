import pytest

from fintrace.shared.company_resolver import normalize_company_code, resolve_company
from fintrace.shared.exceptions import CompanyNotFoundError, InvalidCompanyCodeError


def test_normalizes_suffix_and_exchange() -> None:
    assert normalize_company_code(" 600519.sh ") == ("600519", "SSE")


def test_preserves_leading_zero() -> None:
    assert normalize_company_code("000001.SZ") == ("000001", "SZSE")


def test_rejects_conflicting_suffix() -> None:
    with pytest.raises(InvalidCompanyCodeError, match="conflicts"):
        normalize_company_code("600519.SZ")


def test_rejects_non_six_digit_code() -> None:
    with pytest.raises(InvalidCompanyCodeError):
        normalize_company_code("6005190")


def test_resolves_moutai_with_2026_fallback() -> None:
    company = resolve_company("600519", 2026)
    assert company.company_code == "600519"
    assert company.company_name == "贵州茅台"
    assert company.exchange == "SSE"
    assert company.industry_code == "C15"
    assert company.company_info_year_requested == 2026
    assert company.company_info_year_used == 2025
    assert company.company_info_fallback is True
    assert company.fallback_reason is not None


def test_exact_year_does_not_fallback() -> None:
    company = resolve_company("600519.SH", 2025)
    assert company.company_info_year_used == 2025
    assert company.company_info_fallback is False
    assert company.fallback_reason is None


def test_unknown_company_is_explicit() -> None:
    with pytest.raises(CompanyNotFoundError, match="does not exist"):
        resolve_company("699999", 2025)
