import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class ConfirmationDispatchResult:
    sent_at: datetime
    channel: str
    provider: str
    message_id: str


class ConfirmationService(Protocol):
    def send_confirmation(
        self,
        *,
        phone: str,
        message: str,
        preferred_channel: str | None = None,
    ) -> ConfirmationDispatchResult:
        ...


class LocalConfirmationService:
    def __init__(self, default_channel: str = "sms"):
        self.default_channel = (default_channel or "sms").strip().lower()

    def send_confirmation(
        self,
        *,
        phone: str,
        message: str,
        preferred_channel: str | None = None,
    ) -> ConfirmationDispatchResult:
        channel = (preferred_channel or self.default_channel or "sms").strip().lower()
        sent_at = datetime.utcnow()
        message_id = f"local-{secrets.token_hex(6)}"
        print(
            "[LOCAL_CONFIRMATION] "
            f"channel={channel} phone={phone} message_id={message_id} "
            f"sent_at={sent_at.isoformat()} message={message}"
        )
        return ConfirmationDispatchResult(
            sent_at=sent_at,
            channel=channel,
            provider="local",
            message_id=message_id,
        )


def get_confirmation_service() -> ConfirmationService:
    provider = os.getenv("COMMS_PROVIDER", "local").strip().lower()
    default_channel = os.getenv("COMMS_DEFAULT_CHANNEL", "sms").strip().lower()
    if provider == "local":
        return LocalConfirmationService(default_channel=default_channel)
    return LocalConfirmationService(default_channel=default_channel)
