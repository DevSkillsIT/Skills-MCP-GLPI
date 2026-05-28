"""Tests for normalize_date helper.

Validates tolerance to multiple date formats and natural-language keywords,
ensuring the MCP normalizes whatever shape the LLM sends.
"""

from datetime import datetime, timedelta, date

import pytest

from src.utils.helpers import normalize_date, DateTimeHelper
from src.models.exceptions import ValidationError


class TestNormalizeDateISO:
    def test_iso_format_passes_through(self):
        assert normalize_date("2026-05-26") == "2026-05-26"

    def test_iso_with_time_strips_time(self):
        assert normalize_date("2026-05-26T14:30:00") == "2026-05-26"

    def test_iso_with_space_time_strips_time(self):
        assert normalize_date("2026-05-26 14:30:00") == "2026-05-26"

    def test_iso_with_whitespace_trimmed(self):
        assert normalize_date("  2026-05-26  ") == "2026-05-26"


class TestNormalizeDateBR:
    def test_br_slash_format(self):
        assert normalize_date("26/05/2026") == "2026-05-26"

    def test_br_dash_format(self):
        assert normalize_date("26-05-2026") == "2026-05-26"

    def test_dayfirst_ambiguous_resolved_to_br(self):
        # 03/04/2026 should be April 3rd (BR), not March 4th (US)
        assert normalize_date("03/04/2026") == "2026-04-03"


class TestNormalizeDateKeywords:
    def test_hoje_returns_today(self):
        expected = datetime.now().date().strftime("%Y-%m-%d")
        assert normalize_date("hoje") == expected

    def test_today_returns_today(self):
        expected = datetime.now().date().strftime("%Y-%m-%d")
        assert normalize_date("today") == expected

    def test_ontem_returns_yesterday(self):
        expected = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert normalize_date("ontem") == expected

    def test_yesterday_returns_yesterday(self):
        expected = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert normalize_date("yesterday") == expected

    def test_amanha_returns_tomorrow(self):
        expected = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert normalize_date("amanha") == expected

    def test_amanha_with_tilde_returns_tomorrow(self):
        expected = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert normalize_date("amanhã") == expected

    def test_tomorrow_returns_tomorrow(self):
        expected = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert normalize_date("tomorrow") == expected

    def test_anteontem_returns_two_days_ago(self):
        expected = (datetime.now().date() - timedelta(days=2)).strftime("%Y-%m-%d")
        assert normalize_date("anteontem") == expected

    def test_keyword_case_insensitive(self):
        expected = datetime.now().date().strftime("%Y-%m-%d")
        assert normalize_date("HOJE") == expected
        assert normalize_date("Today") == expected


class TestNormalizeDateEdgeCases:
    def test_none_returns_none(self):
        assert normalize_date(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_date("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_date("   ") is None

    def test_datetime_object_formatted(self):
        dt = datetime(2026, 5, 26, 14, 30, 0)
        assert normalize_date(dt) == "2026-05-26"

    def test_date_object_formatted(self):
        d = date(2026, 5, 26)
        assert normalize_date(d) == "2026-05-26"


class TestNormalizeDateInvalid:
    @pytest.mark.parametrize("bad", [
        "not a date",
        "99/99/9999",
        "maybe tomorrow",
        "xxxx",
        "13/13/2026",  # invalid month
    ])
    def test_invalid_raises_validation_error(self, bad):
        with pytest.raises(ValidationError) as exc_info:
            normalize_date(bad)
        assert "invalida" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()


class TestParseDateRange:
    def test_iso_range(self):
        f, t = DateTimeHelper.parse_date_range("2026-05-01", "2026-05-31")
        assert f == "2026-05-01 00:00:00"
        assert t == "2026-05-31 23:59:59"

    def test_br_range(self):
        f, t = DateTimeHelper.parse_date_range("01/05/2026", "31/05/2026")
        assert f == "2026-05-01 00:00:00"
        assert t == "2026-05-31 23:59:59"

    def test_keyword_range(self):
        today = datetime.now().date().strftime("%Y-%m-%d")
        yesterday = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
        f, t = DateTimeHelper.parse_date_range("ontem", "hoje")
        assert f == f"{yesterday} 00:00:00"
        assert t == f"{today} 23:59:59"

    def test_empty_passthrough(self):
        f, t = DateTimeHelper.parse_date_range(None, None)
        assert f is None
        assert t is None
