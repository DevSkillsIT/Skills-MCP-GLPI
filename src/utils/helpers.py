"""
Utilidades e Helpers - Conforme SPEC.md RNF01
Migrado de logger.py existente + truncagem inteligente e sanitização
"""

import json
import logging
import logging.handlers
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta, date

from dateutil import parser as _date_parser

from src.config import settings
from src.models.exceptions import ValidationError


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
    
    #: Teto de um campo de texto CURTO (nome, status, tipo de ativo, URL).
    SHORT_TEXT_MAX = 10_000

    #: Teto de um campo de TEXTO RICO (descricao do chamado, acompanhamento,
    #: solucao). O `content` do GLPI e LONGTEXT; cortar em 10.000 caracteres
    #: mutilava laudo tecnico e log colado no chamado.
    RICH_TEXT_MAX = 200_000

    def __init__(self):
        """Inicializa sanitizador."""
        # Padrões de limpeza
        self.html_pattern = re.compile(r'<[^<]+?>')
        self.script_pattern = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)
        self.sql_pattern = re.compile(r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION)\b)', re.IGNORECASE)

        # Construcoes que executam codigo no navegador de quem abrir o chamado.
        # Sao removidas SEMPRE, inclusive em texto rico — ao contrario de <p> e
        # <strong>, que sao formatacao legitima do editor do GLPI.
        self.dangerous_html_patterns = [
            re.compile(r'<(script|style|iframe|object|embed|applet|form)[^>]*>.*?</\1>',
                       re.IGNORECASE | re.DOTALL),
            re.compile(r'<(script|style|iframe|object|embed|applet|form|meta|link|base)[^>]*/?>',
                       re.IGNORECASE),
            # on*= handlers: onerror=, onload=, onclick=...
            re.compile(r'\son\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE),
        ]

        # javascript:/vbscript:/data: em href|src. Substituido por um alvo
        # inerte em vez de removido: apagar o atributo inteiro deixava `<a ">`
        # no texto, uma tag quebrada no meio da nota do chamado.
        self.dangerous_url_pattern = re.compile(
            r'(href|src)\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)',
            re.IGNORECASE,
        )
        self.dangerous_scheme_pattern = re.compile(
            r'^\s*["\']?\s*(?:javascript|vbscript|data)\s*:', re.IGNORECASE
        )
        
        # Lista de palavras suspeitas para SQL injection
        self.suspicious_words = [
            'drop', 'delete', 'truncate', 'exec', 'execute', 'script',
            'javascript:', 'vbscript:', 'onload=', 'onerror=',
            'alert(', 'confirm(', 'prompt(', 'eval(', 'expression('
        ]
    
    def sanitize_string(
        self,
        text: str,
        allow_html: bool = False,
        max_length: Optional[int] = None,
    ) -> str:
        """
        Sanitiza string de entrada ANTES de enviar ao GLPI.

        @MX:ANCHOR: este metodo NUNCA aplica html.escape.
        @MX:REASON: escapar e uma responsabilidade de QUEM RENDERIZA, nunca de
        quem grava. Escapando aqui, o texto chegava ao GLPI ja com entidades e o
        GLPI escapava de novo ao salvar: uma nota com `"copia de 3"` era exibida
        no chamado como `&quot;copia de 3&quot;`, literal, para o cliente ler.
        Escape duplo nao e um detalhe cosmetico — corrompe a nota gravada, e nao
        ha instrucao de prompt que conserte, porque o dano acontece depois do
        modelo. Aspas, & e acentos vao para o GLPI exatamente como foram
        escritos; o que sai daqui e o conteudo, nao a sua representacao em HTML.

        Args:
            text: Texto para sanitizar.
            allow_html: True em campo de TEXTO RICO do GLPI (descricao,
                acompanhamento, solucao, comentario), onde <p>/<strong>/<br> sao
                formatacao legitima do editor. False em campo escalar (nome,
                status, tipo), onde tag nenhuma faz sentido.
            max_length: Teto do campo. Default: RICH_TEXT_MAX quando
                allow_html, SHORT_TEXT_MAX caso contrario.

        Returns:
            Texto sanitizado.
        """
        if not text:
            return ""

        # Construcoes executaveis saem sempre — em texto rico tambem.
        for pattern in self.dangerous_html_patterns:
            text = pattern.sub('', text)

        def _neutralise_url(match: "re.Match") -> str:
            attribute, value = match.group(1), match.group(0).split("=", 1)[1]
            if self.dangerous_scheme_pattern.search(value):
                return f'{attribute}="#"'
            return match.group(0)

        text = self.dangerous_url_pattern.sub(_neutralise_url, text)

        # Em campo escalar, qualquer tag remanescente e ruido.
        if not allow_html:
            text = self.html_pattern.sub('', text)

        # Remover caracteres de controle
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')

        # Limitar tamanho para evitar DoS
        limit = max_length or (self.RICH_TEXT_MAX if allow_html else self.SHORT_TEXT_MAX)
        if len(text) > limit:
            # @MX:WARN: o corte precisa dizer QUANTO foi perdido.
            # @MX:REASON: "... [truncated]" no fim de uma nota nao diz se
            # faltaram 10 caracteres ou 40 mil, e quem le a nota no GLPI nao tem
            # como saber o que ficou de fora.
            dropped = len(text) - limit
            logger.warning(
                f"sanitize_string: texto cortado em {limit} caracteres "
                f"({dropped} descartados)"
            )
            text = (
                text[:limit]
                + f"\n\n[TEXTO CORTADO PELO MCP: {dropped} caracteres alem do "
                f"limite de {limit} nao foram enviados ao GLPI]"
            )

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
        # Ex: "a.silva@DOMINIO" (campo contact/Nome Alternativo do Usuário)
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


_DATE_KEYWORDS = {
    "hoje": 0, "today": 0, "now": 0, "agora": 0,
    "ontem": -1, "yesterday": -1,
    "amanha": 1, "amanhã": 1, "tomorrow": 1,
    "anteontem": -2,
}


def normalize_date(value: Optional[Union[str, datetime, date]]) -> Optional[str]:
    """
    Normaliza data em multiplos formatos para ISO 8601 (YYYY-MM-DD).

    Aceita:
        - YYYY-MM-DD (ISO, ja normalizado)
        - DD/MM/YYYY (BR)
        - DD-MM-YYYY
        - MM/DD/YYYY (US, ambiguo — preferimos BR via dayfirst)
        - YYYY-MM-DDTHH:MM:SS (ISO com hora — hora descartada)
        - YYYY-MM-DD HH:MM:SS
        - Strings naturais: 'hoje', 'today', 'ontem', 'yesterday', 'amanha', 'tomorrow', 'anteontem'
        - None ou string vazia -> retorna None
        - datetime/date Python -> formata direto

    Returns:
        String YYYY-MM-DD ou None.

    Raises:
        ValidationError se a string nao puder ser interpretada.
    """
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if not isinstance(value, str):
        value = str(value)
    s = value.strip()
    if not s:
        return None

    # Keywords (case-insensitive)
    key = s.lower()
    if key in _DATE_KEYWORDS:
        target = datetime.now().date() + timedelta(days=_DATE_KEYWORDS[key])
        return target.strftime("%Y-%m-%d")

    # Fast path: already ISO
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Fallback: dateutil with dayfirst=True (BR convention)
    try:
        dt = _date_parser.parse(s, dayfirst=True, fuzzy=False)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, _date_parser.ParserError, OverflowError):
        raise ValidationError(
            f"Data '{value}' invalida. Formatos aceitos: YYYY-MM-DD, DD/MM/YYYY, "
            "DD-MM-YYYY, ISO com hora, ou palavras 'hoje', 'ontem', 'amanha'.",
            "date_format",
        )


class DateTimeHelper:
    """
    Helper para manipulação de datas e horas.
    """

    @staticmethod
    def parse_date_range(
        date_from: Optional[str], date_to: Optional[str]
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Valida e formata range de datas. Aceita multiplos formatos
        (YYYY-MM-DD, DD/MM/YYYY, 'hoje', 'ontem', etc) — normaliza via normalize_date.

        Args:
            date_from: Data inicial (qualquer formato suportado por normalize_date)
            date_to: Data final (idem)

        Returns:
            Tuple (date_from_normalizado, date_to_normalizado) no formato
            "YYYY-MM-DD HH:MM:SS" — from com 00:00:00, to com 23:59:59.
        """
        normalized_from = normalize_date(date_from)
        normalized_to = normalize_date(date_to)

        out_from = f"{normalized_from} 00:00:00" if normalized_from else date_from
        out_to = f"{normalized_to} 23:59:59" if normalized_to else date_to

        return out_from, out_to
    
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
        # @MX:NOTE: entity_id=0 e a root entity valida (ex: "MSP Skills").
        # @MX:REASON: Bug #4 — `not entity_id` rejeitava id=0 como falsy.
        if entity_id is None:
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
            # @MX:NOTE: `is not None` em vez de truthy — preserva entity id=0 (root).
            # @MX:REASON: Bug #4 — entity ID=0 era filtrada como falsy, sumindo da lista.
            return [
                {"id": e.get("id"), "name": e.get("name"), "completename": e.get("completename")}
                for e in entities if isinstance(e, dict) and e.get("id") is not None
            ]
        except Exception as e:
            logger.error(f"EntityResolver: erro ao listar entidades: {e}")
            return []


# Instâncias globais
logger = LoggerService()
response_truncator = ResponseTruncator()
input_sanitizer = InputSanitizer()
entity_resolver = EntityResolver()
