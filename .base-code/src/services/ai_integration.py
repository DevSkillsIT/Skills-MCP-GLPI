"""
AI Integration Service - Conforme auditoria GAP-CRIT-01
Implementa AIJobStore com TTL e interfaces para integração IA.
"""

import time
import uuid
from typing import Dict, Any, Optional
from src.logger import logger


class AIJobStore:
    """
    Armazena jobs de análise IA com TTL.
    Conforme auditoria GAP-CRIT-01: AIJobStore com TTL.
    """
    
    def __init__(self, ttl_seconds: int = 3600):
        """Inicializa o job store com TTL configurável."""
        self._jobs: Dict[str, tuple] = {}
        self._ttl = ttl_seconds
        logger.info(f"AIJobStore initialized with TTL={ttl_seconds}s")
    
    def set(self, job_id: str, data: dict):
        """Armazena um job com timestamp."""
        self._jobs[job_id] = (time.time(), data)
        logger.debug(f"Job stored: {job_id}")
    
    def get(self, job_id: str) -> Optional[dict]:
        """Obtém um job se ainda válido (não expirado)."""
        if job_id not in self._jobs:
            return None
        
        ts, data = self._jobs[job_id]
        if time.time() - ts > self._ttl:
            # Job expirado, remover
            self._jobs.pop(job_id, None)
            logger.debug(f"Job expired and removed: {job_id}")
            return None
        
        return data
    
    def delete(self, job_id: str) -> bool:
        """Remove um job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            logger.debug(f"Job deleted: {job_id}")
            return True
        return False
    
    def cleanup_expired(self) -> int:
        """Remove todos os jobs expirados."""
        now = time.time()
        expired = [
            job_id for job_id, (ts, _) in self._jobs.items()
            if now - ts > self._ttl
        ]
        for job_id in expired:
            del self._jobs[job_id]
        
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired jobs")
        return len(expired)


class AIIntegrationService:
    """
    Serviço de integração com IA para análise de tickets.
    Conforme auditoria GAP-CRIT-01: Interfaces IA.
    """
    
    def __init__(self):
        """Inicializa o serviço de integração IA."""
        self.job_store = AIJobStore(ttl_seconds=3600)
        self._agents_configured = False
        logger.info("AIIntegrationService initialized")
    
    async def trigger_analysis(self, ticket_id: int) -> str:
        """
        Dispara análise IA para um ticket.
        Retorna job_id para consulta posterior.
        """
        job_id = f"ai_job_{uuid.uuid4().hex[:12]}"
        
        # Armazenar job com status inicial
        self.job_store.set(job_id, {
            "ticket_id": ticket_id,
            "status": "queued",
            "created_at": time.time(),
            "result": None
        })
        
        logger.info(f"AI analysis triggered for ticket {ticket_id}: {job_id}")
        
        # Se não há agentes configurados, marcar como tal
        if not self._agents_configured:
            self.job_store.set(job_id, {
                "ticket_id": ticket_id,
                "status": "no_agents_configured",
                "created_at": time.time(),
                "result": None
            })
        
        return job_id
    
    async def get_analysis_result(self, job_id: str) -> Optional[dict]:
        """Obtém resultado de uma análise IA."""
        return self.job_store.get(job_id)
    
    async def publish_ai_response(self, job_id: str, response: dict) -> bool:
        """Publica resposta de análise IA."""
        job = self.job_store.get(job_id)
        if not job:
            logger.warning(f"Job not found for publishing: {job_id}")
            return False
        
        job["status"] = "completed"
        job["result"] = response
        job["completed_at"] = time.time()
        self.job_store.set(job_id, job)
        
        logger.info(f"AI response published for job: {job_id}")
        return True
    
    def configure_agents(self, agents: list):
        """Configura agentes IA disponíveis."""
        self._agents_configured = len(agents) > 0
        logger.info(f"AI agents configured: {len(agents)}")


# Instância global do serviço de integração IA
ai_integration = AIIntegrationService()
