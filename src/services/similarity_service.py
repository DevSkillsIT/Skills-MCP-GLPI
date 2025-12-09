"""
Similarity Service - Conforme SPEC.md RF03
Extrai e adapta TextSimilarity da fonte Anfaia com ProcessPoolExecutor
Implementa 4 algoritmos: Jaccard, Cosine, Levenshtein, TF-IDF
"""

import math
import re
import unicodedata
from typing import Dict, List, Tuple, Optional, Set, Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
from difflib import SequenceMatcher

from src.config import settings
from src.logger import logger
from src.models.exceptions import SimilarityError


class TextSimilarity:
    """
    Classe para calcular similaridade entre textos usando múltiplos algoritmos.
    Extraído e adaptado da fonte Anfaia conforme SPEC.md seção 4.3
    """
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """Normaliza o texto para comparação."""
        if not text:
            return ""
        
        # Remover acentos e converter para minúsculas
        text = unicodedata.normalize('NFD', text.lower())
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        
        # Remover caracteres especiais e espaços extras
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @staticmethod
    def extract_keywords(text: str, min_length: int = 3) -> Set[str]:
        """Extrai palavras-chave relevantes do texto."""
        if not text:
            return set()
        
        # Stop words em português, inglês e espanhol
        stop_words = {
            # Português
            'o', 'a', 'os', 'as', 'de', 'da', 'do', 'dos', 'das', 'que', 'e', 'em', 'um', 
            'uma', 'uns', 'umas', 'para', 'com', 'sem', 'como', 'por', 'no', 'na', 'nos',
            'nas', 'se', 'te', 'lo', 'le', 'lhe', 'mais', 'mas', 'muito', 'muita', 'muitos',
            'muitas', 'pouco', 'pouca', 'poucos', 'poucas', 'bem', 'mal', 'já', 'ainda',
            'também', 'também', 'nem', 'só', 'não', 'sim', 'ou', 'outra', 'outro', 'outras',
            'outros', 'todo', 'toda', 'todos', 'todas', 'qual', 'quais', 'qualquer', 'quaisquer',
            'algum', 'alguma', 'alguns', 'algumas', 'nenhum', 'nenhuma', 'nenhuns', 'nenhumas',
            'todo', 'toda', 'todos', 'todas', 'cada', 'qual', 'qualquer', 'muito', 'pouco',
            # Inglês
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
            'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after', 'above',
            'below', 'between', 'among', 'under', 'over', 'above', 'can', 'cannot', 'will',
            'just', 'should', 'could', 'would', 'might', 'must', 'shall', 'may', 'this',
            'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what',
            'which', 'who', 'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both',
            'few', 'more', 'most', 'other', 'some', 'such', 'only', 'own', 'same', 'so',
            'than', 'too', 'very', 'just', 'now',
            # Espanhol
            'el', 'la', 'de', 'que', 'y', 'a', 'en', 'un', 'es', 'se', 'no', 'te', 'lo',
            'le', 'da', 'su', 'por', 'son', 'con', 'para', 'al', 'una', 'del', 'los', 'las',
            'si', 'me', 'ya', 'muy', 'mas', 'pero', 'como', 'ser', 'hay', 'este', 'esta',
            'esto', 'todos', 'todo', 'tiene', 'hacer', 'estar', 'un', 'una', 'unos', 'unas',
            'mi', 'mis', 'tu', 'tus', 'su', 'sus', 'nuestro', 'nuestra', 'nuestros', 'nuestras'
        }
        
        normalized = TextSimilarity.normalize_text(text)
        words = normalized.split()
        
        # Filtrar palavras curtas e stop words
        keywords = {w for w in words if len(w) >= min_length and w not in stop_words}
        
        return keywords
    
    @staticmethod
    def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
        """Calcula similaridade de Jaccard entre dois conjuntos."""
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0.0
    
    @staticmethod
    def cosine_similarity(text1: str, text2: str) -> float:
        """Calcula similaridade cosseno usando TF-IDF simplificado."""
        if not text1 or not text2:
            return 0.0
        
        words1 = TextSimilarity.normalize_text(text1).split()
        words2 = TextSimilarity.normalize_text(text2).split()
        
        if not words1 or not words2:
            return 0.0
        
        # Criar vocabulário conjunto
        vocab = set(words1 + words2)
        
        # Calcular vetores TF
        vec1 = [words1.count(word) for word in vocab]
        vec2 = [words2.count(word) for word in vocab]
        
        # Calcular similaridade cosseno
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    @staticmethod
    def levenshtein_distance(text1: str, text2: str) -> int:
        """Calcula distância de Levenshtein entre dois textos."""
        if not text1:
            return len(text2) if text2 else 0
        if not text2:
            return len(text1)
        
        text1 = TextSimilarity.normalize_text(text1)
        text2 = TextSimilarity.normalize_text(text2)
        
        m, n = len(text1), len(text2)
        
        # Matriz de distâncias
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        # Inicializar primeira linha e coluna
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        
        # Preencher matriz
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if text1[i - 1] == text2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = 1 + min(
                        dp[i - 1][j],      # deletar
                        dp[i][j - 1],      # inserir
                        dp[i - 1][j - 1]   # substituir
                    )
        
        return dp[m][n]
    
    @staticmethod
    def levenshtein_similarity(text1: str, text2: str) -> float:
        """Calcula similaridade baseada em distância de Levenshtein."""
        if not text1 and not text2:
            return 1.0
        if not text1 or not text2:
            return 0.0
        
        distance = TextSimilarity.levenshtein_distance(text1, text2)
        max_len = max(len(text1), len(text2))
        
        return 1.0 - (distance / max_len) if max_len > 0 else 1.0
    
    @staticmethod
    def tfidf_similarity(text1: str, text2: str) -> float:
        """Calcula similaridade TF-IDF melhorada."""
        if not text1 or not text2:
            return 0.0
        
        words1 = TextSimilarity.normalize_text(text1).split()
        words2 = TextSimilarity.normalize_text(text2).split()
        
        if not words1 or not words2:
            return 0.0
        
        # Contar frequências
        freq1 = Counter(words1)
        freq2 = Counter(words2)
        
        # Criar vocabulário conjunto
        vocab = set(words1 + words2)
        
        # Calcular TF-IDF simplificado
        def tfidf(word, freq, total_words, vocab_size):
            tf = freq[word] / total_words
            # IDF simplificado (log de documentos totais / documentos com a palavra)
            df = sum(1 for f in [freq1, freq2] if word in f)
            idf = math.log(len([freq1, freq2]) / (df + 1)) + 1
            return tf * idf
        
        # Calcular vetores TF-IDF
        vec1 = [tfidf(word, freq1, len(words1), len(vocab)) for word in vocab]
        vec2 = [tfidf(word, freq2, len(words2), len(vocab)) for word in vocab]
        
        # Similaridade cosseno
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    @staticmethod
    def sequence_similarity(text1: str, text2: str) -> float:
        """Calcula similaridade usando SequenceMatcher."""
        if not text1 or not text2:
            return 0.0
        
        norm1 = TextSimilarity.normalize_text(text1)
        norm2 = TextSimilarity.normalize_text(text2)
        
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    @staticmethod
    def combined_similarity(text1: str, text2: str, title1: str = "", title2: str = "") -> float:
        """Calcula similaridade combinada usando múltiplos algoritmos."""
        if not text1 or not text2:
            return 0.0
        
        # Pesos para cada algoritmo conforme SPEC.md (BUG-IMP-01/BUG-IMP-02)
        # Auditoria: 0.30/0.30/0.25/0.15 para sequence/cosine/jaccard/title_bonus
        weights = {
            'sequence': 0.30,
            'cosine': 0.30,
            'jaccard': 0.25,
            'title_bonus': 0.15
        }
        
        # Similaridade de sequência
        seq_sim = TextSimilarity.sequence_similarity(text1, text2)
        
        # Similaridade cosseno
        cos_sim = TextSimilarity.cosine_similarity(text1, text2)
        
        # Similaridade Jaccard com keywords
        keywords1 = TextSimilarity.extract_keywords(text1)
        keywords2 = TextSimilarity.extract_keywords(text2)
        jac_sim = TextSimilarity.jaccard_similarity(keywords1, keywords2)
        
        # Bônus por similaridade em títulos
        title_sim = 0.0
        if title1 and title2:
            title_sim = TextSimilarity.sequence_similarity(title1, title2)
        
        # Combinar métricas conforme SPEC (BUG-IMP-01: apenas 4 pesos)
        combined = (
            weights['sequence'] * seq_sim +
            weights['cosine'] * cos_sim +
            weights['jaccard'] * jac_sim +
            weights['title_bonus'] * title_sim
        )
        
        return min(1.0, combined)


class SimilarityService:
    """
    Serviço de similaridade com ProcessPoolExecutor para performance.
    Conforme SPEC.md RF03: ProcessPoolExecutor com max_workers configurável
    """
    
    def __init__(self):
        """Inicializa o serviço de similaridade."""
        self.max_workers = settings.similarity_max_workers
        self.max_items = settings.similarity_max_items
        
        logger.info(f"SimilarityService initialized: max_workers={self.max_workers}, max_items={self.max_items}")
    
    def _calculate_single_similarity(self, args: Tuple[str, str, str, str, str]) -> Dict[str, Any]:
        """
        Calcula similaridade para um único par de textos.
        Função auxiliar para ProcessPoolExecutor.
        
        Args:
            args: (id1, text1, title1, id2, text2, title2)
        
        Returns:
            Dicionário com resultados da similaridade
        """
        id1, text1, title1, id2, text2, title2 = args
        
        try:
            # Calcular todas as similaridades
            results = {
                'id1': id1,
                'id2': id2,
                'sequence': TextSimilarity.sequence_similarity(text1, text2),
                'cosine': TextSimilarity.cosine_similarity(text1, text2),
                'jaccard': TextSimilarity.jaccard_similarity(
                    TextSimilarity.extract_keywords(text1),
                    TextSimilarity.extract_keywords(text2)
                ),
                'levenshtein': TextSimilarity.levenshtein_similarity(text1, text2),
                'tfidf': TextSimilarity.tfidf_similarity(text1, text2),
                'combined': TextSimilarity.combined_similarity(text1, text2, title1, title2)
            }
            
            return results
            
        except Exception as e:
            logger.error(f"Error calculating similarity for {id1}-{id2}: {e}")
            return {
                'id1': id1,
                'id2': id2,
                'error': str(e),
                'combined': 0.0
            }
    
    async def find_similar_tickets(
        self,
        target_ticket: Dict[str, str],
        candidate_tickets: List[Dict[str, str]],
        threshold: float = 0.3,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Encontra tickets similares usando ProcessPoolExecutor.
        
        Args:
            target_ticket: Ticket alvo com 'title' e 'content'
            candidate_tickets: Lista de tickets candidatos
            threshold: Limiar mínimo de similaridade
            max_results: Número máximo de resultados
        
        Returns:
            Lista de tickets similares ordenados por similaridade
        """
        if not candidate_tickets:
            return []
        
        # Limitar número de candidatos para performance
        if len(candidate_tickets) > self.max_items:
            candidate_tickets = candidate_tickets[:self.max_items]
            logger.warning(f"Limited candidate tickets to {self.max_items} for performance")
        
        target_text = target_ticket.get('content', '')
        target_title = target_ticket.get('title', '')
        
        # Preparar argumentos para processamento paralelo
        args_list = []
        for ticket in candidate_tickets:
            args = (
                ticket.get('id', ''),
                target_text,
                target_title,
                ticket.get('id', ''),
                ticket.get('content', ''),
                ticket.get('title', '')
            )
            args_list.append(args)
        
        # Processar em paralelo com ProcessPoolExecutor
        similarities = []
        
        try:
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                # Submeter todas as tarefas
                future_to_args = {
                    executor.submit(self._calculate_single_similarity, args): args
                    for args in args_list
                }
                
                # Coletar resultados
                for future in as_completed(future_to_args):
                    try:
                        result = future.result(timeout=30)  # Timeout por segurança
                        if 'error' not in result and result['combined'] >= threshold:
                            similarities.append(result)
                    except Exception as e:
                        args = future_to_args[future]
                        logger.error(f"Parallel processing failed for args {args[0]}-{args[3]}: {e}")
        
        except Exception as e:
            logger.error(f"ProcessPoolExecutor failed: {e}")
            # Fallback para processamento sequencial
            for args in args_list:
                try:
                    result = self._calculate_single_similarity(args)
                    if 'error' not in result and result['combined'] >= threshold:
                        similarities.append(result)
                except Exception as e:
                    logger.error(f"Sequential processing failed: {e}")
        
        # Ordenar por similaridade combinada
        similarities.sort(key=lambda x: x.get('combined', 0), reverse=True)
        
        # Limitar resultados
        results = similarities[:max_results]
        
        logger.info(f"Found {len(results)} similar tickets above threshold {threshold}")
        return results
    
    async def calculate_similarity_matrix(
        self,
        tickets: List[Dict[str, str]],
        threshold: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Calcula matriz de similaridade entre múltiplos tickets.
        
        Args:
            tickets: Lista de tickets
            threshold: Limiar mínimo de similaridade
        
        Returns:
            Matriz de similaridades
        """
        if len(tickets) < 2:
            return []
        
        # Limitar para performance
        if len(tickets) > self.max_items:
            tickets = tickets[:self.max_items]
        
        # Gerar todos os pares únicos
        pairs = []
        for i in range(len(tickets)):
            for j in range(i + 1, len(tickets)):
                ticket1 = tickets[i]
                ticket2 = tickets[j]
                
                args = (
                    ticket1.get('id', ''),
                    ticket1.get('content', ''),
                    ticket1.get('title', ''),
                    ticket2.get('id', ''),
                    ticket2.get('content', ''),
                    ticket2.get('title', '')
                )
                pairs.append(args)
        
        # Processar em paralelo
        similarities = []
        
        try:
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_args = {
                    executor.submit(self._calculate_single_similarity, args): args
                    for args in pairs
                }
                
                for future in as_completed(future_to_args):
                    try:
                        result = future.result(timeout=30)
                        if 'error' not in result and result['combined'] >= threshold:
                            similarities.append(result)
                    except Exception as e:
                        logger.error(f"Matrix calculation failed: {e}")
        
        except Exception as e:
            logger.error(f"Similarity matrix calculation failed: {e}")
        
        # Ordenar por similaridade
        similarities.sort(key=lambda x: x.get('combined', 0), reverse=True)
        
        logger.info(f"Calculated {len(similarities)} similarity pairs above threshold {threshold}")
        return similarities
    
    def get_service_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do serviço."""
        return {
            "max_workers": self.max_workers,
            "max_items": self.max_items,
            "algorithms": [
                "sequence",
                "cosine", 
                "jaccard",
                "levenshtein",
                "tfidf",
                "combined"
            ]
        }


# Instância global do serviço de similaridade
similarity_service = SimilarityService()
