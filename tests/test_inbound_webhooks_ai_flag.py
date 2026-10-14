"""Inbound /webhooks/ticket/* must not pretend to queue work the server will not do.

With ENABLE_AI_ANALYSIS=false (the default) the created-ticket webhook still called
the in-memory AI stub and answered ``received`` plus a ``job_id`` -- the sender then
believed an analysis was queued. Now the reply says analysis is disabled and no job
is created.
"""
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import settings
from src.main import app

SECRET = "default-webhook-secret"
ENDPOINTS = ("created", "updated", "closed", "followup")


def _post(client, event, ticket_id=321):
    ts = str(int(time.time()))
    body = json.dumps({"ticket_id": ticket_id})
    sig = "sha256=" + hmac.new(SECRET.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return client.post(
        f"/webhooks/ticket/{event}",
        content=body,
        headers={"Content-Type": "application/json", "X-GLPI-Timestamp": ts, "X-GLPI-Signature": sig},
    )


@pytest.fixture
def client():
    return TestClient(app)


class TestAnalysisDisabled:
    @pytest.mark.parametrize("event", ENDPOINTS)
    def test_reply_says_no_analysis_and_carries_no_job(self, client, monkeypatch, event):
        monkeypatch.setattr(settings, "enable_ai_analysis", False)
        with patch("src.main.ai_integration.trigger_analysis", AsyncMock(return_value="job-x")) as trigger:
            response = _post(client, event)
        assert response.status_code == 200
        data = response.json()
        assert data["ticket_id"] == 321
        assert data["analysis"] == "disabled"
        assert "job_id" not in data
        trigger.assert_not_awaited()


class TestAnalysisEnabled:
    def test_created_queues_a_job_and_says_so(self, client, monkeypatch):
        monkeypatch.setattr(settings, "enable_ai_analysis", True)
        with patch("src.main.ai_integration.trigger_analysis", AsyncMock(return_value="job-x")) as trigger:
            response = _post(client, "created")
        data = response.json()
        assert data["status"] == "received"
        assert data["job_id"] == "job-x"
        assert data["analysis"] == "queued"
        trigger.assert_awaited_once_with(321)

    @pytest.mark.parametrize("event", ("updated", "closed", "followup"))
    def test_other_events_never_queue_analysis(self, client, monkeypatch, event):
        monkeypatch.setattr(settings, "enable_ai_analysis", True)
        with patch("src.main.ai_integration.trigger_analysis", AsyncMock(return_value="job-x")) as trigger:
            data = _post(client, event).json()
        assert "job_id" not in data
        trigger.assert_not_awaited()
