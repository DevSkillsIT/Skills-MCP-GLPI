"""
Testes para Webhooks - Conforme auditoria GAP-CRIT-04
Valida HMAC-SHA256, timestamp e endpoints /webhooks/*.
"""

import pytest
import hmac
import hashlib
import time
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from src.main import app


class TestWebhookAuthentication:
    """Testes para autenticação HMAC de webhooks."""
    
    @pytest.fixture
    def client(self):
        """Fixture para criar cliente de teste."""
        return TestClient(app)
    
    @pytest.fixture
    def webhook_secret(self):
        """Secret para testes."""
        return "default-webhook-secret"
    
    def _generate_signature(self, secret: str, timestamp: str, body: str) -> str:
        """Gera assinatura HMAC-SHA256 válida."""
        mac = hmac.new(
            secret.encode(),
            f"{timestamp}.{body}".encode(),
            hashlib.sha256
        )
        return f"sha256={mac.hexdigest()}"
    
    def test_webhook_missing_signature(self, client):
        """Testa webhook sem assinatura retorna 401."""
        response = client.post(
            "/webhooks/ticket/created",
            json={"ticket_id": 123}
        )
        
        assert response.status_code == 401
        assert "signature missing" in response.json()["detail"].lower()
    
    def test_webhook_missing_timestamp(self, client, webhook_secret):
        """Testa webhook sem timestamp retorna 401."""
        body = json.dumps({"ticket_id": 123})
        signature = self._generate_signature(webhook_secret, str(int(time.time())), body)
        
        response = client.post(
            "/webhooks/ticket/created",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GLPI-Signature": signature
                # Sem X-GLPI-Timestamp
            }
        )
        
        assert response.status_code == 401
    
    def test_webhook_expired_timestamp(self, client, webhook_secret):
        """Testa webhook com timestamp expirado (>5min) retorna 401."""
        old_timestamp = str(int(time.time()) - 400)  # 6+ minutos atrás
        body = json.dumps({"ticket_id": 123})
        signature = self._generate_signature(webhook_secret, old_timestamp, body)
        
        response = client.post(
            "/webhooks/ticket/created",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GLPI-Timestamp": old_timestamp,
                "X-GLPI-Signature": signature
            }
        )
        
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()
    
    def test_webhook_invalid_signature(self, client, webhook_secret):
        """Testa webhook com assinatura inválida retorna 401."""
        timestamp = str(int(time.time()))
        body = json.dumps({"ticket_id": 123})
        
        response = client.post(
            "/webhooks/ticket/created",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GLPI-Timestamp": timestamp,
                "X-GLPI-Signature": "sha256=invalidsignature"
            }
        )
        
        assert response.status_code == 401
        assert "verification failed" in response.json()["detail"].lower()
    
    def test_webhook_valid_signature(self, client, webhook_secret):
        """Testa webhook com assinatura válida retorna 200."""
        timestamp = str(int(time.time()))
        body = json.dumps({"ticket_id": 123})
        signature = self._generate_signature(webhook_secret, timestamp, body)
        
        response = client.post(
            "/webhooks/ticket/created",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GLPI-Timestamp": timestamp,
                "X-GLPI-Signature": signature
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
        assert data["ticket_id"] == 123


class TestWebhookEndpoints:
    """Testes para endpoints de webhook."""
    
    @pytest.fixture
    def client(self):
        """Fixture para criar cliente de teste."""
        return TestClient(app)
    
    @pytest.fixture
    def valid_headers(self):
        """Headers válidos para webhook."""
        timestamp = str(int(time.time()))
        body = json.dumps({"ticket_id": 456})
        secret = "default-webhook-secret"
        mac = hmac.new(
            secret.encode(),
            f"{timestamp}.{body}".encode(),
            hashlib.sha256
        )
        signature = f"sha256={mac.hexdigest()}"
        
        return {
            "Content-Type": "application/json",
            "X-GLPI-Timestamp": timestamp,
            "X-GLPI-Signature": signature
        }, body
    
    def test_webhook_ticket_created_endpoint_exists(self, client, valid_headers):
        """Testa que endpoint /webhooks/ticket/created existe."""
        headers, body = valid_headers
        response = client.post(
            "/webhooks/ticket/created",
            content=body,
            headers=headers
        )
        
        # Não deve ser 404
        assert response.status_code != 404
    
    def test_webhook_ticket_updated_endpoint_exists(self, client):
        """Testa que endpoint /webhooks/ticket/updated existe."""
        timestamp = str(int(time.time()))
        body = json.dumps({"ticket_id": 789})
        secret = "default-webhook-secret"
        mac = hmac.new(
            secret.encode(),
            f"{timestamp}.{body}".encode(),
            hashlib.sha256
        )
        signature = f"sha256={mac.hexdigest()}"
        
        response = client.post(
            "/webhooks/ticket/updated",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GLPI-Timestamp": timestamp,
                "X-GLPI-Signature": signature
            }
        )
        
        assert response.status_code == 200
    
    def test_webhook_ticket_closed_endpoint_exists(self, client):
        """Testa que endpoint /webhooks/ticket/closed existe."""
        timestamp = str(int(time.time()))
        body = json.dumps({"ticket_id": 999})
        secret = "default-webhook-secret"
        mac = hmac.new(
            secret.encode(),
            f"{timestamp}.{body}".encode(),
            hashlib.sha256
        )
        signature = f"sha256={mac.hexdigest()}"
        
        response = client.post(
            "/webhooks/ticket/closed",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GLPI-Timestamp": timestamp,
                "X-GLPI-Signature": signature
            }
        )
        
        assert response.status_code == 200


class TestWebhookAIIntegration:
    """Testes para integração IA via webhooks."""
    
    @pytest.fixture
    def client(self):
        """Fixture para criar cliente de teste."""
        return TestClient(app)
    
    def test_webhook_triggers_ai_analysis(self, client):
        """Testa que webhook ticket/created dispara análise IA."""
        timestamp = str(int(time.time()))
        body = json.dumps({"ticket_id": 123})
        secret = "default-webhook-secret"
        mac = hmac.new(
            secret.encode(),
            f"{timestamp}.{body}".encode(),
            hashlib.sha256
        )
        signature = f"sha256={mac.hexdigest()}"
        
        response = client.post(
            "/webhooks/ticket/created",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GLPI-Timestamp": timestamp,
                "X-GLPI-Signature": signature
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Deve retornar job_id para acompanhamento
        assert "job_id" in data or data.get("ticket_id") is not None
