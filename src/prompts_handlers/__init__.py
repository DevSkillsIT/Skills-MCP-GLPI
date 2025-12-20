"""
MCP GLPI - Prompts Handlers Package
Módulo de handlers de prompts profissionais para o MCP GLPI.
"""

from src.prompts_handlers.prompts import (
    prompt_handler,
    handle_list_prompts,
    handle_get_prompt,
    PROMPTS_CATALOG
)

__all__ = [
    'prompt_handler',
    'handle_list_prompts',
    'handle_get_prompt',
    'PROMPTS_CATALOG'
]
