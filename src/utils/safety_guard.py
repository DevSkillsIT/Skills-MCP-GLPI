"""
Safety Guard - Proteção para operações destrutivas
Implementação baseada no padrão do whm-cpanel MCP

Este módulo requer confirmação explícita para operações perigosas como:
- delete_ticket
- delete_asset
- delete_user
- delete_group

Configuração via variáveis de ambiente:
- MCP_SAFETY_GUARD: "true" para ativar (padrão: desativado)
- MCP_SAFETY_TOKEN: Token de confirmação (mínimo 8 caracteres)
"""

import os
import hmac
from pathlib import Path
from typing import Optional, Tuple
from src.utils.helpers import logger
from src.models.exceptions import ValidationError


def _load_env_file():
    """Carrega variáveis do .env se existir."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip()
                # Só define se não existir
                if key not in os.environ:
                    os.environ[key] = val


# Carregar .env ao importar o módulo
_load_env_file()


class SafetyGuard:
    """
    Gerenciador de segurança para operações destrutivas.
    
    Quando ativado, requer:
    - confirmationToken: Token que deve corresponder ao MCP_SAFETY_TOKEN
    - reason: Motivo da operação (mínimo 10 caracteres)
    """
    
    # Operações que requerem confirmação
    PROTECTED_OPERATIONS = {
        "delete_ticket": "Deletar ticket permanentemente",
        "delete_asset": "Deletar asset permanentemente", 
        "delete_user": "Deletar usuário permanentemente",
        "delete_group": "Deletar grupo permanentemente",
        "delete_webhook": "Deletar webhook permanentemente"
    }
    
    MIN_TOKEN_LENGTH = 8
    MIN_REASON_LENGTH = 10
    
    def __init__(self):
        """Inicializa o Safety Guard lendo configurações do ambiente."""
        self._guard_enabled = os.getenv("MCP_SAFETY_GUARD", "false").lower() == "true"
        self._safety_token = os.getenv("MCP_SAFETY_TOKEN", "")
        
        if self._guard_enabled:
            if not self._safety_token:
                logger.warning("MCP_SAFETY_GUARD is enabled but MCP_SAFETY_TOKEN is not set!")
                self._guard_enabled = False
            elif len(self._safety_token) < self.MIN_TOKEN_LENGTH:
                logger.warning(f"MCP_SAFETY_TOKEN must be at least {self.MIN_TOKEN_LENGTH} characters!")
                self._guard_enabled = False
            else:
                logger.info("Safety Guard is ENABLED for destructive operations")
        else:
            logger.info("Safety Guard is DISABLED (set MCP_SAFETY_GUARD=true to enable)")
    
    @property
    def is_enabled(self) -> bool:
        """Verifica se o guard está ativado."""
        return self._guard_enabled
    
    def is_protected_operation(self, operation: str) -> bool:
        """Verifica se a operação requer confirmação."""
        return operation in self.PROTECTED_OPERATIONS
    
    def get_protection_message(self, operation: str) -> str:
        """Retorna mensagem descritiva da operação protegida."""
        return self.PROTECTED_OPERATIONS.get(operation, "Operação destrutiva")
    
    def _tokens_match(self, provided_token: str) -> bool:
        """
        Comparação timing-safe dos tokens.
        Usa hmac.compare_digest para evitar timing attacks.
        """
        if not provided_token or not self._safety_token:
            return False
        
        # Converter para bytes para comparação segura
        provided_bytes = provided_token.encode('utf-8')
        expected_bytes = self._safety_token.encode('utf-8')
        
        return hmac.compare_digest(provided_bytes, expected_bytes)
    
    def require_confirmation(
        self,
        operation: str,
        confirmation_token: Optional[str] = None,
        reason: Optional[str] = None,
        target_id: Optional[int] = None,
        target_type: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Valida se a operação destrutiva pode prosseguir.
        
        Args:
            operation: Nome da operação (ex: "delete_ticket")
            confirmation_token: Token de confirmação fornecido
            reason: Motivo para a operação
            target_id: ID do objeto sendo afetado
            target_type: Tipo do objeto (para logging)
        
        Returns:
            Tuple[bool, Optional[str]]: (permitido, mensagem_erro)
        
        Raises:
            ValidationError: Se a confirmação for inválida
        """
        # Se guard não está ativado, permite tudo
        if not self._guard_enabled:
            return True, None
        
        # Se operação não é protegida, permite
        if not self.is_protected_operation(operation):
            return True, None
        
        # Verificar token
        if not confirmation_token:
            error_msg = (
                f"SAFETY GUARD: Operação '{operation}' requer confirmação. "
                f"Forneça 'confirmationToken' e 'reason' (mín. {self.MIN_REASON_LENGTH} caracteres). "
                f"Ação: {self.get_protection_message(operation)}"
            )
            if target_id:
                error_msg += f" [ID: {target_id}]"
            logger.warning(f"Safety Guard blocked {operation}: no token provided")
            raise ValidationError(error_msg, "confirmationToken")
        
        # Verificar se token corresponde
        if not self._tokens_match(confirmation_token):
            logger.warning(f"Safety Guard blocked {operation}: invalid token")
            raise ValidationError(
                f"SAFETY GUARD: Token de confirmação inválido para '{operation}'",
                "confirmationToken"
            )
        
        # Verificar reason
        if not reason:
            raise ValidationError(
                f"SAFETY GUARD: Motivo ('reason') é obrigatório para '{operation}'",
                "reason"
            )
        
        reason = reason.strip()
        if len(reason) < self.MIN_REASON_LENGTH:
            raise ValidationError(
                f"SAFETY GUARD: Motivo deve ter pelo menos {self.MIN_REASON_LENGTH} caracteres "
                f"(fornecido: {len(reason)} caracteres)",
                "reason"
            )
        
        # Log da operação autorizada
        log_msg = f"Safety Guard AUTHORIZED {operation}"
        if target_type and target_id:
            log_msg += f" on {target_type} ID {target_id}"
        log_msg += f" - Reason: {reason[:50]}{'...' if len(reason) > 50 else ''}"
        logger.info(log_msg)
        
        return True, None
    
    def get_status(self) -> dict:
        """Retorna status do Safety Guard para diagnóstico."""
        return {
            "enabled": self._guard_enabled,
            "token_configured": bool(self._safety_token),
            "protected_operations": list(self.PROTECTED_OPERATIONS.keys()),
            "min_reason_length": self.MIN_REASON_LENGTH,
            "min_token_length": self.MIN_TOKEN_LENGTH
        }


# Instância global do Safety Guard
safety_guard = SafetyGuard()


def require_safety_confirmation(
    operation: str,
    confirmation_token: Optional[str] = None,
    reason: Optional[str] = None,
    target_id: Optional[int] = None,
    target_type: Optional[str] = None
) -> bool:
    """
    Função helper para verificar confirmação de segurança.
    
    Uso:
        require_safety_confirmation(
            "delete_ticket",
            confirmation_token=kwargs.get("confirmationToken"),
            reason=kwargs.get("reason"),
            target_id=ticket_id,
            target_type="Ticket"
        )
    
    Raises:
        ValidationError: Se confirmação inválida ou ausente
    
    Returns:
        True se autorizado
    """
    allowed, _ = safety_guard.require_confirmation(
        operation=operation,
        confirmation_token=confirmation_token,
        reason=reason,
        target_id=target_id,
        target_type=target_type
    )
    return allowed
