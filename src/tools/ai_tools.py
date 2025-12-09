"""
MCP Tools - IA (RF06)
Implementa trigger_ai_analysis, get_ai_analysis_result, publish_ai_response.
"""

from typing import Dict, Any
from src.services.ai_integration import ai_integration
from src.models.exceptions import ValidationError, GLPIError
from src.utils.helpers import logger, response_truncator


class AITools:
    """Tools de integração IA conforme SPEC RF06."""

    async def trigger_ai_analysis(self, ticket_id: int) -> Dict[str, Any]:
        """Dispara análise IA para um ticket."""
        try:
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("ticket_id must be positive", "ticket_id")
            job_id = await ai_integration.trigger_analysis(ticket_id)
            return {"job_id": job_id, "status": "processing"}
        except (ValidationError, GLPIError):
            raise
        except Exception as e:
            logger.error(f"trigger_ai_analysis unexpected error: {e}")
            raise GLPIError(500, f"Failed to trigger ai analysis: {str(e)}")

    async def get_ai_analysis_result(self, job_id: str) -> Dict[str, Any]:
        """Obtém resultado de uma análise IA."""
        try:
            if not job_id:
                raise ValidationError("job_id is required", "job_id")
            result = await ai_integration.get_analysis_result(job_id)
            if result is None:
                raise GLPIError(404, "Job not found", {"job_id": job_id})
            return response_truncator.truncate_json_response(result)
        except (ValidationError, GLPIError):
            raise
        except Exception as e:
            logger.error(f"get_ai_analysis_result unexpected error: {e}")
            raise GLPIError(500, f"Failed to get ai analysis result: {str(e)}")

    async def publish_ai_response(self, job_id: str, response: Dict[str, Any]) -> Dict[str, Any]:
        """Publica resposta IA em um job existente."""
        try:
            if not job_id:
                raise ValidationError("job_id is required", "job_id")
            ok = await ai_integration.publish_ai_response(job_id, response)
            if not ok:
                raise GLPIError(404, "Job not found", {"job_id": job_id})
            return {"job_id": job_id, "status": "completed"}
        except (ValidationError, GLPIError):
            raise
        except Exception as e:
            logger.error(f"publish_ai_response unexpected error: {e}")
            raise GLPIError(500, f"Failed to publish ai response: {str(e)}")


# Instância global
ai_tools = AITools()
