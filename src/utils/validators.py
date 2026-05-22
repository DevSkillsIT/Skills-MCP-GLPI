"""
Input validators for MCP tools.

SPEC-GLPI-ENHANCE-001/F02+F08 — Section 4.2, 4.8
"""


def validate_positive_int(value, field_name: str = "id", allow_zero: bool = False) -> dict:
    """
    Validate that value is a positive integer.
    GLPI API uses integer IDs, not UUIDs.

    Args:
        value: The value to validate.
        field_name: Name of the field for error messages.
        allow_zero: If True, accepts 0 (useful for GLPI root entity id=0).

    Returns:
        {"valid": True, "value": int} on success
        {"valid": False, "error": str} on failure
    """
    try:
        int_val = int(value)
        min_value = 0 if allow_zero else 1
        if int_val < min_value:
            raise ValueError()
        return {"valid": True, "value": int_val}
    except (ValueError, TypeError):
        bound_hint = "nao negativo (ex: 0, 42)" if allow_zero else "positivo (ex: 42)"
        return {
            "valid": False,
            "error": (
                f"{field_name} invalido: '{value}'. "
                f"Esperado inteiro {bound_hint}. "
                f"Use a tool de busca correspondente (glpi_search_ticket_requests, "
                f"glpi_search_admin_resources, glpi_search_asset_inventory) para obter IDs validos."
            ),
        }


def validate_non_negative_int(value, field_name: str = "id") -> dict:
    """
    Validate that value is a non-negative integer (>= 0).
    Useful for GLPI entity_id where 0 is the root entity.
    """
    return validate_positive_int(value, field_name, allow_zero=True)


def create_mcp_error(problem: str, expected: str, example: str) -> dict:
    """
    Create standardized 3-part MCP error.
    Pattern: MELHORES-PRATICAS Section 9.2.

    Returns:
        MCP error response with isError=True
    """
    return {
        "content": [
            {
                "type": "text",
                "text": f"{problem}. {expected}. {example}",
            }
        ],
        "isError": True,
    }
