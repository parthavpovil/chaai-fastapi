"""
Unit tests for Resend email webhook handlers
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers.webhooks import (
    handle_email_sent,
    handle_email_delivered,
    handle_email_delayed,
    handle_email_complained,
    handle_email_bounced,
    handle_email_opened,
    handle_email_clicked,
    _persist_email_log,
)
from app.models.email_log import EmailLog


def make_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def make_event_data(email_id="evt_123", to="user@example.com", subject="Hello"):
    return {"email_id": email_id, "to": to, "subject": subject}


class TestPersistEmailLog:
    @pytest.mark.asyncio
    async def test_creates_email_log_and_commits(self):
        db = make_db()
        data = make_event_data()

        await _persist_email_log(db, "sent", data)

        assert db.add.called
        log_arg = db.add.call_args[0][0]
        assert isinstance(log_arg, EmailLog)
        assert log_arg.event_type == "sent"
        assert log_arg.email_id == "evt_123"
        assert log_arg.recipient == "user@example.com"
        assert log_arg.subject == "Hello"
        assert log_arg.extra_data == data
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_list_recipient(self):
        db = make_db()
        data = {"email_id": "e1", "to": ["a@b.com", "c@d.com"], "subject": "Multi"}

        await _persist_email_log(db, "sent", data)

        log_arg = db.add.call_args[0][0]
        assert log_arg.recipient == "a@b.com, c@d.com"

    @pytest.mark.asyncio
    async def test_generates_uuid_when_email_id_missing(self):
        db = make_db()
        data = {"to": "u@x.com"}

        await _persist_email_log(db, "sent", data)

        log_arg = db.add.call_args[0][0]
        assert log_arg.email_id  # some non-empty string was generated


class TestHandleEmailSent:
    @pytest.mark.asyncio
    async def test_persists_sent_log(self):
        db = make_db()
        data = make_event_data()

        await handle_email_sent(data, db)

        db.add.assert_called_once()
        log_arg = db.add.call_args[0][0]
        assert log_arg.event_type == "sent"
        db.commit.assert_awaited_once()


class TestHandleEmailDelivered:
    @pytest.mark.asyncio
    async def test_persists_delivered_log(self):
        db = make_db()
        await handle_email_delivered(make_event_data(), db)

        log_arg = db.add.call_args[0][0]
        assert log_arg.event_type == "delivered"


class TestHandleEmailDelayed:
    @pytest.mark.asyncio
    async def test_persists_delayed_log(self):
        db = make_db()
        await handle_email_delayed(make_event_data(), db)

        log_arg = db.add.call_args[0][0]
        assert log_arg.event_type == "delayed"


class TestHandleEmailComplained:
    @pytest.mark.asyncio
    async def test_persists_complained_log(self):
        db = make_db()
        await handle_email_complained(make_event_data(), db)

        log_arg = db.add.call_args[0][0]
        assert log_arg.event_type == "complained"

    @pytest.mark.asyncio
    async def test_logs_warning_on_complaint(self):
        db = make_db()
        with patch("app.routers.webhooks.logger") as mock_logger:
            await handle_email_complained(make_event_data(), db)
            mock_logger.warning.assert_called_once()


class TestHandleEmailBounced:
    @pytest.mark.asyncio
    async def test_persists_bounced_log(self):
        db = make_db()
        data = {**make_event_data(), "bounce_type": "soft"}
        await handle_email_bounced(data, db)

        log_arg = db.add.call_args[0][0]
        assert log_arg.event_type == "bounced"

    @pytest.mark.asyncio
    async def test_hard_bounce_logs_warning(self):
        db = make_db()
        data = {**make_event_data(), "bounce_type": "hard"}
        with patch("app.routers.webhooks.logger") as mock_logger:
            await handle_email_bounced(data, db)
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_soft_bounce_logs_info(self):
        db = make_db()
        data = {**make_event_data(), "bounce_type": "soft"}
        with patch("app.routers.webhooks.logger") as mock_logger:
            await handle_email_bounced(data, db)
            mock_logger.info.assert_called_once()


class TestHandleEmailOpened:
    @pytest.mark.asyncio
    async def test_persists_opened_log(self):
        db = make_db()
        await handle_email_opened(make_event_data(), db)

        log_arg = db.add.call_args[0][0]
        assert log_arg.event_type == "opened"


class TestHandleEmailClicked:
    @pytest.mark.asyncio
    async def test_persists_clicked_log(self):
        db = make_db()
        data = {**make_event_data(), "link": "https://example.com"}
        await handle_email_clicked(data, db)

        log_arg = db.add.call_args[0][0]
        assert log_arg.event_type == "clicked"
