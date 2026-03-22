"""
Utilidades e Helpers - Conforme SPEC.md RNF01
Migrado de logger.py existente + truncagem inteligente e sanitização
"""

import json
import logging
import logging.handlers
import re
import html
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

from src.config import settings
from src.models.exceptions import GLPIError


class LoggerService:
    """Serviço de logging com suporte a arquivos e console."""

    _instance = None
    _logger = None

    def __new__(cls):
        """Implementação do padrão Singleton."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Inicializa o logger."""
        self._logger = logging.getLogger("mcp-glpi")
        self._logger.setLevel(getattr(logging, settings.log_level))

        # Cria diretório de logs se não existir
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Handler para arquivo com rotação
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)

        # Handler para console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, settings.log_level))

        # Formato detalhado
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Adiciona handlers se não existirem
        if not self._logger.handlers:
            self._logger.addHandler(file_handler)
            self._logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        """Retorna a instância do logger."""
        return self._logger

    def debug(self, message: str, **kwargs):
        """Log de debug."""
        self._logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs):
        """Log de informação."""
        self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Log de aviso."""
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs):
        """Log de erro."""
        self._logger.error(message, **kwargs)

    def critical(self, message: str, **kwargs):
        """Log crítico."""
        self._logger.critical(message, **kwargs)


class ResponseTruncator:
    """
    Utilitário de truncagem inteligente de respostas.
    Conforme SPEC.md RNF01: truncagem de respostas > 50KB
    """
    
    def __init__(self, max_size: int = None):
        """Inicializa truncador com tamanho máximo."""
        self.max_size = max_size or settings.max_response_size
        
        # Campos importantes que nunca devem ser truncados
        self.important_fields = [
            'id', 'name', 'title', 'status', 'error', 'success', 
            'count', 'total', 'entity', 'is_active', 'is_recursive',
            'date_creation', 'date_mod', 'timestamp', 'pagination'
        ]
    
    def truncate_json_response(self, data: Any, max_size: int = None) -> Any:
        """
        Trunca inteligentemente uma resposta JSON muito volumosa.
        Baseado no código fonte Docker conforme SPEC.md
        
        Args:
            data: Dados JSON para truncar
            max_size: Tamanho máximo (usa default se não especificado)
        
        Returns:
            Dados truncados ou mensagem informativa
        """
        max_size = max_size or self.max_size
        
        # Converter para JSON para verificar tamanho
        try:
            json_str = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # Se não conseguir serializar, retorna como está
            return data
        
        # Se já pequeno, não modificar
        if len(json_str) <= max_size:
            return data
        
        # Se é dict, truncar inteligentemente
        if isinstance(data, dict):
            return self._truncate_dict(data, json_str, max_size)
        
        # Se é list, truncar lista
        elif isinstance(data, list):
            return self._truncate_list(data, json_str, max_size)
        
        # Último recurso: retornar mensagem de erro
        return {
            "truncated": True,
            "original_size": len(json_str),
            "max_size": max_size,
            "hint": "Response too large. Use filters or pagination to reduce size.",
            "original_type": type(data).__name__
        }
    
    def _truncate_dict(self, data: Dict[str, Any], json_str: str, max_size: int) -> Dict[str, Any]:
        """Trunca dicionário mantendo campos importantes."""
        truncated = {}
        total_size = 0
        
        # Primeiro: incluir campos importantes
        for key, value in data.items():
            if key in self.important_fields:
                truncated[key] = value
                total_size += len(json.dumps({key: value}, ensure_ascii=False, default=str))
        
        # Segundo: incluir outros campos se houver espaço
        for key, value in data.items():
            if key not in self.important_fields:
                value_size = len(json.dumps({key: value}, ensure_ascii=False, default=str))
                
                if total_size + value_size <= max_size * 0.8:  # Deixar margem
                    truncated[key] = value
                    total_size += value_size
                else:
                    # Truncar valor se for list ou dict grande
                    if isinstance(value, list) and len(value) > 10:
                        truncated[key] = value[:5] + [f"... {len(value) - 5} items truncated"]
                    elif isinstance(value, dict) and len(str(value)) > 1000:
                        truncated[key] = f"<Object with {len(value)} keys - truncated>"
                    else:
                        truncated[key] = value
        
        # Verificar tamanho final
        final_json = json.dumps(truncated, ensure_ascii=False, default=str)
        if len(final_json) <= max_size:
            return truncated
        else:
            # Se ainda muito grande, retornar resumo
            return {
                "truncated": True,
                "original_size": len(json_str),
                "max_size": max_size,
                "important_fields": {k: v for k, v in truncated.items() if k in self.important_fields},
                "summary": f"Response too large ({len(json_str)} bytes). Key count: {len(data)}",
                "available_keys": list(data.keys())[:20]
            }
    
    def _truncate_list(self, data: List[Any], json_str: str, max_size: int) -> List[Any]:
        """Trunca lista mantendo itens importantes."""
        if len(data) <= 10:
            return data
        
        # Manter primeiros itens e adicionar hint
        truncated = data[:5]
        truncated.append({
            "truncation_info": f"... {len(data) - 5} items truncated",
            "original_count": len(data),
            "hint": "Use pagination to get all items"
        })
        
        return truncated
    
    def get_truncation_stats(self, original_data: Any, truncated_data: Any) -> Dict[str, Any]:
        """Retorna estatísticas da truncagem."""
        try:
            original_size = len(json.dumps(original_data, ensure_ascii=False, default=str))
            truncated_size = len(json.dumps(truncated_data, ensure_ascii=False, default=str))
            
            return {
                "original_size": original_size,
                "truncated_size": truncated_size,
                "reduction_percentage": round((1 - truncated_size / original_size) * 100, 2),
                "was_truncated": original_size > self.max_size
            }
        except (TypeError, ValueError):
            return {
                "error": "Could not calculate truncation stats",
                "was_truncated": False
            }


class InputSanitizer:
    """
    Utilitário de sanitização de inputs.
    Conforme SPEC.md: validação e limpeza de dados de entrada
    """
    
    def __init__(self):
        """Inicializa sanitizador."""
        # Padrões de limpeza
        self.html_pattern = re.compile(r'<[^<]+?>')
        self.script_pattern = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)
        self.sql_pattern = re.compile(r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION)\b)', re.IGNORECASE)
        
        # Lista de palavras suspeitas para SQL injection
        self.suspicious_words = [
            'drop', 'delete', 'truncate', 'exec', 'execute', 'script',
            'javascript:', 'vbscript:', 'onload=', 'onerror=',
            'alert(', 'confirm(', 'prompt(', 'eval(', 'expression('
        ]
    
    def sanitize_string(self, text: str, allow_html: bool = False) -> str:
        """
        Sanitiza string de entrada.
        
        Args:
            text: Texto para sanitizar
            allow_html: Se permite HTML (default: False)
        
        Returns:
            Texto sanitizado
        """
        if not text:
            return ""
        
        # Remover scripts maliciosos
        text = self.script_pattern.sub('', text)
        
        # Remover HTML se não permitido
        if not allow_html:
            text = self.html_pattern.sub('', text)
        
        # Escapar HTML para segurança
        text = html.escape(text)
        
        # Remover caracteres de controle
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
        
        # Limitar tamanho para evitar DoS
        if len(text) > 10000:
            text = text[:10000] + "... [truncated]"
        
        return text.strip()
    
    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitiza nome de arquivo.
        
        Args:
            filename: Nome do arquivo
        
        Returns:
            Nome sanitizado
        """
        if not filename:
            return "unnamed"
        
        # Remover caracteres perigosos
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        # Remover caminhos relativos
        filename = filename.replace('..', '').replace('./', '').replace('../', '')
        
        # Limitar tamanho
        if len(filename) > 255:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            if ext:
                max_name_len = 255 - len(ext) - 1
                filename = name[:max_name_len] + '.' + ext
            else:
                filename = filename[:255]
        
        return filename.strip()
    
    def validate_sql_input(self, input_text: str) -> bool:
        """
        Valida input contra SQL injection.
        
        Args:
            input_text: Texto para validar
        
        Returns:
            True se seguro, False se suspeito
        """
        if not input_text:
            return True
        
        # Converter para minúsculas para verificação
        lower_text = input_text.lower()
        
        # Verificar palavras suspeitas
        for word in self.suspicious_words:
            if word in lower_text:
                return False
        
        # Verificar padrões SQL
        if self.sql_pattern.search(input_text):
            return False
        
        # Verificar aspas e comentários SQL
        dangerous_chars = ["'", '"', ';', '--', '/*', '*/', 'xp_', 'sp_']
        for char in dangerous_chars:
            if char in input_text:
                return False
        
        return True
    
    def sanitize_search_query(self, query: str) -> str:
        """
        Sanitiza query de busca.
        
        Args:
            query: Query de busca
        
        Returns:
            Query sanitizada
        """
        if not query:
            return ""
        
        # Sanitização básica
        query = self.sanitize_string(query, allow_html=False)
        
        # Permitir caracteres especiais de busca mas remover perigosos
        # NOTA: Incluímos '.' e '@' para permitir buscas por email/contact
        # Ex: "joana.rodrigues@GRUPOWINK" (campo contact/Nome Alternativo do Usuário)
        allowed_special = ['*', '?', '[', ']', '{', '}', '(', ')', '-', '+', '"', '.', '@', '_']
        query = ''.join(
            char for char in query
            if char.isalnum() or char.isspace() or char in allowed_special
        )
        
        # Limitar tamanho
        if len(query) > 500:
            query = query[:500]
        
        return query.strip()
    
    def validate_email(self, email: str) -> bool:
        """
        Valida formato de email.
        
        Args:
            email: Email para validar
        
        Returns:
            True se válido, False se inválido
        """
        if not email:
            return False
        
        # Padrão básico de email
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        return bool(email_pattern.match(email))
    
    def validate_phone(self, phone: str) -> str:
        """
        Valida e formata número de telefone.
        
        Args:
            phone: Telefone para validar
        
        Returns:
            Telefone formatado ou string vazia se inválido
        """
        if not phone:
            return ""
        
        # Remover tudo exceto números e caracteres válidos
        phone = re.sub(r'[^\d\+\-\s\(\)]', '', phone)
        
        # Validar formato básico
        if len(re.sub(r'\D', '', phone)) < 10:  # Pelo menos 10 dígitos
            return ""
        
        return phone.strip()


class PaginationHelper:
    """
    Helper para paginação inteligente.
    Conforme SPEC.md: paginação com metadados e hints
    """
    
    @staticmethod
    def build_pagination_params(
        offset: int = 0,
        limit: int = None,
        sort_field: str = None,
        sort_order: str = "ASC"
    ) -> Dict[str, Any]:
        """
        Constrói parâmetros de paginação.
        
        Args:
            offset: Offset para paginação
            limit: Limite de itens por página
            sort_field: Campo para ordenação
            sort_order: Ordem (ASC/DESC)
        
        Returns:
            Dicionário de parâmetros
        """
        limit = limit or settings.default_page_size
        
        params = {
            "range": f"{offset}-{offset + limit - 1}",
            "range_limit": limit,
            "range_offset": offset
        }
        
        if sort_field:
            params["sort"] = sort_field
            params["order"] = sort_order.upper()
        
        return params
    
    @staticmethod
    def build_pagination_response(
        items: List[Any],
        total_count: int,
        offset: int,
        limit: int,
        endpoint: str = ""
    ) -> Dict[str, Any]:
        """
        Constrói resposta com metadados de paginação.
        
        Args:
            items: Lista de itens
            total_count: Total de itens
            offset: Offset atual
            limit: Limite por página
            endpoint: Endpoint para hints
        
        Returns:
            Resposta com metadados
        """
        has_more = offset + limit < total_count
        next_offset = offset + limit if has_more else None
        current_page = (offset // limit) + 1
        total_pages = (total_count + limit - 1) // limit
        
        response = {
            "data": items,
            "pagination": {
                "total": total_count,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                "next_offset": next_offset,
                "current_page": current_page,
                "total_pages": total_pages
            }
        }
        
        # Adicionar hints se houver muitas páginas
        if total_pages > 10:
            response["hint"] = f"Large result set ({total_count} items, {total_pages} pages). Consider using filters to reduce results."
        
        # Adicionar link para próxima página se existir
        if endpoint and has_more:
            response["pagination"]["next_page_url"] = f"{endpoint}?offset={next_offset}&limit={limit}"
        
        return response
    
    @staticmethod
    def validate_pagination_params(offset: int, limit: int) -> tuple[int, int]:
        """
        Valida e corrige parâmetros de paginação.
        
        Args:
            offset: Offset solicitado
            limit: Limite solicitado
        
        Returns:
            Tuple (offset_validado, limit_validado)
        """
        # Validar offset
        if offset < 0:
            offset = 0
        
        # Validar limit
        if limit <= 0:
            limit = settings.default_page_size
        elif limit > 1000:  # Limite máximo para proteção
            limit = 1000
        
        return offset, limit


class DateTimeHelper:
    """
    Helper para manipulação de datas e horas.
    """
    
    @staticmethod
    def parse_date_range(date_from: str, date_to: str) -> tuple[str, str]:
        """
        Valida e formata range de datas.
        
        Args:
            date_from: Data inicial (YYYY-MM-DD)
            date_to: Data final (YYYY-MM-DD)
        
        Returns:
            Tuple (date_from_validado, date_to_validado)
        """
        try:
            if date_from:
                from_dt = datetime.strptime(date_from, "%Y-%m-%d")
                date_from = from_dt.strftime("%Y-%m-%d 00:00:00")
            
            if date_to:
                to_dt = datetime.strptime(date_to, "%Y-%m-%d")
                date_to = to_dt.strftime("%Y-%m-%d 23:59:59")
            
            return date_from, date_to
            
        except ValueError:
            raise ValidationError("Invalid date format. Use YYYY-MM-DD", "date_format")
    
    @staticmethod
    def format_glpi_datetime(dt: datetime) -> str:
        """
        Formata datetime para formato GLPI.
        
        Args:
            dt: Datetime para formatar
        
        Returns:
            String formatada para GLPI
        """
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    
    @staticmethod
    def is_future_date(date_str: str) -> bool:
        """
        Verifica se data é futura.
        
        Args:
            date_str: Data para verificar (YYYY-MM-DD)
        
        Returns:
            True se futura, False se passada ou presente
        """
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt > datetime.now()
        except ValueError:
            return False


class EntityResolver:
    """
    Helper para resolver entity_name para entity_id.
    Permite filtrar por nome de entidade/cliente sem precisar saber o ID.
    """

    def __init__(self):
        """Inicializa o resolver."""
        self._entity_cache: Dict[str, int] = {}
        self._cache_timestamp: datetime = None
        self._cache_ttl: int = 300  # 5 minutos

    async def resolve_entity_name(self, entity_name: str) -> Optional[int]:
        """
        Resolve nome de entidade para ID.
        Busca case-insensitive e com match parcial.

        Args:
            entity_name: Nome da entidade (cliente) para buscar

        Returns:
            entity_id se encontrado, None se não encontrado
        """
        if not entity_name:
            return None

        # Importar aqui para evitar circular import
        from src.services.admin_service import admin_service

        logger.info(f"EntityResolver: buscando entidade '{entity_name}'")

        try:
            # Buscar todas entidades
            entities = await admin_service.list_entities(limit=500, use_cache=True)

            # Normalizar nome para busca
            search_name = entity_name.lower().strip()

            # Busca exata primeiro (case-insensitive)
            for entity in entities:
                if isinstance(entity, dict):
                    name = entity.get("name", "").lower()
                    completename = entity.get("completename", "").lower()

                    if name == search_name or completename == search_name:
                        entity_id = entity.get("id")
                        logger.info(f"EntityResolver: match exato - '{entity_name}' = ID {entity_id}")
                        return entity_id

            # Busca parcial (contains)
            for entity in entities:
                if isinstance(entity, dict):
                    name = entity.get("name", "").lower()
                    completename = entity.get("completename", "").lower()

                    if search_name in name or search_name in completename:
                        entity_id = entity.get("id")
                        logger.info(f"EntityResolver: match parcial - '{entity_name}' encontrado em '{entity.get('name')}' = ID {entity_id}")
                        return entity_id

            # Não encontrado
            logger.warning(f"EntityResolver: entidade '{entity_name}' não encontrada")
            return None

        except Exception as e:
            logger.error(f"EntityResolver: erro ao buscar entidade '{entity_name}': {e}")
            return None

    async def get_entity_name_by_id(self, entity_id: int) -> Optional[str]:
        """
        Obtém nome da entidade pelo ID.

        Args:
            entity_id: ID da entidade

        Returns:
            Nome da entidade ou None
        """
        if not entity_id:
            return None

        from src.services.admin_service import admin_service

        try:
            entity = await admin_service.get_entity(entity_id)
            return entity.get("name") if entity else None
        except Exception:
            return None

    async def list_available_entities(self) -> List[Dict[str, Any]]:
        """
        Lista todas as entidades disponíveis para referência.
        Útil quando o usuário não sabe o nome exato.

        Returns:
            Lista de entidades com id e name
        """
        from src.services.admin_service import admin_service

        try:
            entities = await admin_service.list_entities(limit=500, use_cache=True)
            return [
                {"id": e.get("id"), "name": e.get("name"), "completename": e.get("completename")}
                for e in entities if isinstance(e, dict) and e.get("id")
            ]
        except Exception as e:
            logger.error(f"EntityResolver: erro ao listar entidades: {e}")
            return []


# Instâncias globais
logger = LoggerService()
response_truncator = ResponseTruncator()
input_sanitizer = InputSanitizer()
entity_resolver = EntityResolver()
