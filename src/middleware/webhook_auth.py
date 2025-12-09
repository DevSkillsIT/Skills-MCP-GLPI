"""
Webhook Authentication Middleware - HMAC-SHA256 verification
Conforme auditoria BUG-CRIT-01/BUG-CRIT-02: Implementar webhooks com HMAC
"""

import hmac
import hashlib
import time
from fastapi import Request, HTTPException

from src.config import settings
from src.logger import logger


async def verify_webhook_signature(request: Request):
    """
    Verifica assinatura HMAC-SHA256 de webhooks.
    Conforme auditoria: validar timestamp e signature.
    
    Headers esperados:
    - X-GLPI-Timestamp: Unix timestamp da requisição
    - X-GLPI-Signature: sha256=<hmac_hex>
    """
    ts = request.headers.get("X-GLPI-Timestamp")
    sig = request.headers.get("X-GLPI-Signature", "")
    
    if not ts or not sig:
        logger.warning("Webhook signature missing")
        raise HTTPException(status_code=401, detail="Webhook signature missing")
    
    # Validar timestamp (máximo 5 minutos de diferença)
    try:
        timestamp = int(ts)
        if abs(time.time() - timestamp) > 300:
            logger.warning(f"Webhook timestamp expired: {ts}")
            raise HTTPException(status_code=401, detail="Webhook timestamp expired")
    except ValueError:
        logger.warning(f"Invalid webhook timestamp: {ts}")
        raise HTTPException(status_code=401, detail="Invalid webhook timestamp")
    
    # Obter body da requisição
    body = await request.body()
    
    # Calcular HMAC esperado
    secret = getattr(settings, 'webhook_secret', 'default-secret')
    expected = hmac.new(
        secret.encode(),
        f"{ts}.{body.decode()}".encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Comparar assinaturas de forma segura
    provided_sig = sig.replace("sha256=", "")
    if not hmac.compare_digest(expected, provided_sig):
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=401, detail="Webhook signature verification failed")
    
    logger.debug("Webhook signature verified successfully")


def verify_signature(secret: str, body: bytes, timestamp: str, signature: str):
    """
    Função auxiliar para verificar assinatura HMAC.
    Conforme auditoria BUG-CRIT-02.
    """
    if abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(401, "Webhook timestamp expired")
    
    mac = hmac.new(
        secret.encode(), 
        msg=f"{timestamp}.{body.decode()}".encode(), 
        digestmod=hashlib.sha256
    )
    expected = f"sha256={mac.hexdigest()}"
    
    if not hmac.compare_digest(expected, signature or ""):
        raise HTTPException(401, "Webhook signature invalid")
