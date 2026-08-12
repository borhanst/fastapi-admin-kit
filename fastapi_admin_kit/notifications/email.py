"""Email notification channel — built-in SMTP provider.

Uses the stdlib ``smtplib`` so email works out of the box with minimal
configuration (host, port, credentials, from-address).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmailResult:
    """Outcome of an :meth:`EmailProvider.send` call."""

    message_id: str
    status: str = "sent"
    to: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class EmailDeliveryError(Exception):
    """Raised when an email provider fails to send."""


class EmailProvider(ABC):
    """Abstract interface for email notification providers."""

    name: str = "base"

    @abstractmethod
    async def send(
        self,
        to: str,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> EmailResult:
        """Send an email to *to*.

        At least one of *html* or *text* must be provided.
        """


class SMTPEmailProvider(EmailProvider):
    """Send email via an SMTP server.

    Args:
        host: SMTP server hostname.
        port: SMTP server port.
        username: SMTP username (optional).
        password: SMTP password (optional).
        from_address: Sender address used in the ``From`` header.
        from_name: Optional display name for the sender.
        use_tls: Use ``SMTP_SSL`` (default True).
        timeout: Socket timeout in seconds.
    """

    name = "smtp"

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_address: str = "no-reply@example.com",
        from_name: str | None = None,
        use_tls: bool = True,
        timeout: int = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_address = from_address
        self.from_name = from_name
        self.use_tls = use_tls
        self.timeout = timeout

    async def send(
        self,
        to: str,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> EmailResult:
        if not html and not text:
            raise EmailDeliveryError("At least one of html or text must be provided.")

        def _send() -> EmailResult:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.utils import formataddr
            from smtplib import SMTP

            message = MIMEMultipart("alternative")
            from_name = self.from_name or self.from_address
            message["From"] = formataddr((from_name, self.from_address))
            message["To"] = to
            message["Subject"] = subject
            if cc:
                message["Cc"] = ", ".join(cc)
            recipients = [to] + list(cc or []) + list(bcc or [])

            if text:
                message.attach(MIMEText(text, "plain", "utf-8"))
            if html:
                message.attach(MIMEText(html, "html", "utf-8"))

            with SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(message, to_addrs=recipients)

            return EmailResult(
                message_id=f"{self.host}:{self.port}:{to}",
                status="sent",
                to=to,
            )

        try:
            import asyncio

            return await asyncio.to_thread(_send)
        except EmailDeliveryError:
            raise
        except Exception as exc:
            raise EmailDeliveryError(f"SMTP send failed: {exc}") from exc
