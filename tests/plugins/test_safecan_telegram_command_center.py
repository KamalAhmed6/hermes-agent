"""Deterministic SafeCan Telegram command-center controls."""

from __future__ import annotations

import asyncio
import json


def _adapter(monkeypatch, tmp_path):
    from plugins.platforms.telegram.adapter import TelegramAdapter

    adapter = object.__new__(TelegramAdapter)
    monkeypatch.setattr(adapter, "_SAFECAN_EOD_ROOT", str(tmp_path / "eod"))
    monkeypatch.setattr(adapter, "_SAFECAN_PROJECT_MAP", str(tmp_path / "routing.json"))
    monkeypatch.setattr(adapter, "_SAFECAN_DELEGATION_QUEUE", str(tmp_path / "delegations.jsonl"))
    return adapter


def test_safecan_reports_are_evidence_only(monkeypatch, tmp_path):
    adapter = _adapter(monkeypatch, tmp_path)
    date_dir = tmp_path / "eod" / "2026-09-28"
    date_dir.mkdir(parents=True)
    (date_dir / "summary.json").write_text(json.dumps({
        "report_date": "2026-09-28",
        "reports": [{"statement_count": 3, "media_message_count": 2}],
    }), encoding="utf-8")

    response = adapter._safecan_latest_report()

    assert "Evidence updates: 3" in response
    assert "Photo-bearing messages: 2" in response
    assert "not completion, billing, payroll, payout, or client-acceptance" in response


def test_safecan_project_routing_does_not_claim_completion(monkeypatch, tmp_path):
    adapter = _adapter(monkeypatch, tmp_path)
    (tmp_path / "routing.json").write_text(json.dumps([
        {"project_name": "Project A"}, {"chat_name": "Project B"},
    ]), encoding="utf-8")

    response = adapter._safecan_project_routing()

    assert "Configured WhatsApp project mappings: 2" in response
    assert "does not establish operational completion or financial status" in response


def test_delegate_is_queue_only_and_sets_private_permissions(monkeypatch, tmp_path):
    adapter = _adapter(monkeypatch, tmp_path)

    job_id = adapter._enqueue_safecan_delegation("Review a source discrepancy")
    record = json.loads((tmp_path / "delegations.jsonl").read_text(encoding="utf-8"))

    assert job_id == record["job_id"]
    assert record["status"] == "AI_ANALYSIS_PENDING"
    assert "No completion, billing" in record["boundary"]
    assert (tmp_path / "delegations.jsonl").stat().st_mode & 0o777 == 0o600


def test_status_checks_the_active_user_collector(monkeypatch, tmp_path):
    adapter = _adapter(monkeypatch, tmp_path)
    calls = []
    sent = []

    async def state(*args, user_service=False):
        calls.append((args, user_service))
        return "active"

    async def send(chat_id, text, reply_to=None):
        sent.append((chat_id, text, reply_to))

    class Chat:
        id = 123

    class Message:
        chat = Chat()
        message_id = 456

    monkeypatch.setattr(adapter, "_safecan_systemd_state", state)
    monkeypatch.setattr(adapter, "send", send)
    asyncio.run(adapter._send_safecan_server_status(Message()))

    assert (("safecan-whatsapp-collector-user.service",), True) in calls
    assert all("safecan-whatsapp-collector.service" not in args for args, _ in calls)
    assert "SafeCan server check: online" in sent[0][1]
