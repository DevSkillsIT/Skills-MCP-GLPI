"""
Input validators for MCP tools.

SPEC-GLPI-ENHANCE-001/F02+F08 — Section 4.2, 4.8
"""


def validate_positive_int(value, field_name: str = "id") -> dict:
    """
    Validate that value is a positive integer.
    GLPI API uses integer IDs, not UUIDs.

    Returns:
        {"valid": True, "value": int} on success
        {"valid": False, "error": str} on failure
    """
    try:
        int_val = int(value)
        if int_val <= 0:
            raise ValueError()
        return {"valid": True, "value": int_val}
    except (ValueError, TypeError):
        return {
            "valid": False,
            "error": (
                f"{field_name} invalido: '{value}'. "
                f"Esperado inteiro positivo (ex: 42). "
                f"Use glpi_search_tickets para obter IDs validos."
            ),
        }


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
