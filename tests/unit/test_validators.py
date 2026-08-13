"""
Unit tests for src/utils/validators.py

Tests validate_positive_int and create_mcp_error functions.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")


from src.utils.validators import create_mcp_error, validate_positive_int


# === validate_positive_int ===


class TestValidatePositiveInt:
    """Tests for validate_positive_int validator."""

    def test_valid_int(self) -> None:
        """Valid integer 42 returns valid=True with value=42."""
        result = validate_positive_int(42)
        assert result == {"valid": True, "value": 42}

    def test_valid_string_number(self) -> None:
        """Valid string '42' is coerced to int and returns valid=True."""
        result = validate_positive_int("42")
        assert result == {"valid": True, "value": 42}

    def test_zero_is_invalid(self) -> None:
        """Zero is not a positive integer."""
        result = validate_positive_int(0)
        assert result["valid"] is False
        assert "error" in result

    def test_negative_is_invalid(self) -> None:
        """Negative number -1 is not a positive integer."""
        result = validate_positive_int(-1)
        assert result["valid"] is False
        assert "error" in result

    def test_non_numeric_string_is_invalid(self) -> None:
        """Non-numeric string 'abc' cannot be converted."""
        result = validate_positive_int("abc")
        assert result["valid"] is False
        assert "error" in result

    def test_none_is_invalid(self) -> None:
        """None value cannot be converted to int."""
        result = validate_positive_int(None)
        assert result["valid"] is False
        assert "error" in result

    def test_empty_string_is_invalid(self) -> None:
        """Empty string cannot be converted to int."""
        result = validate_positive_int("")
        assert result["valid"] is False
        assert "error" in result

    def test_float_truncates_to_int(self) -> None:
        """Float 3.14 is truncated to int(3) which is positive."""
        result = validate_positive_int(3.14)
        assert result["valid"] is True
        assert result["value"] == 3

    def test_custom_field_name_in_error(self) -> None:
        """Custom field_name appears in error message."""
        result = validate_positive_int("bad", field_name="ticket_id")
        assert result["valid"] is False
        assert "ticket_id" in result["error"]

    def test_large_positive_int(self) -> None:
        """Large positive integer is valid."""
        result = validate_positive_int(999999)
        assert result == {"valid": True, "value": 999999}

    def test_string_one_is_valid(self) -> None:
        """String '1' (boundary) is valid."""
        result = validate_positive_int("1")
        assert result == {"valid": True, "value": 1}


# === create_mcp_error ===


class TestCreateMcpError:
    """Tests for create_mcp_error standardized error builder."""

    def test_returns_dict_with_content_and_is_error(self) -> None:
        """Result has 'content' list and isError=True."""
        result = create_mcp_error(
            "ID invalido",
            "Esperado inteiro positivo",
            "Exemplo: 42",
        )
        assert isinstance(result, dict)
        assert "content" in result
        assert isinstance(result["content"], list)
        assert result["isError"] is True

    def test_content_text_contains_all_three_parts(self) -> None:
        """The text field contains problem, expected, and example."""
        problem = "Parametro ausente"
        expected = "Envie ticket_id"
        example = "Ex: ticket_id=10"
        result = create_mcp_error(problem, expected, example)
        text = result["content"][0]["text"]
        assert problem in text
        assert expected in text
        assert example in text

    def test_content_has_single_text_entry(self) -> None:
        """Content array has exactly one entry of type 'text'."""
        result = create_mcp_error("a", "b", "c")
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"

    def test_text_format_is_dot_separated(self) -> None:
        """The three parts are joined with '. ' separators."""
        result = create_mcp_error("P", "E", "X")
        assert result["content"][0]["text"] == "P. E. X"
