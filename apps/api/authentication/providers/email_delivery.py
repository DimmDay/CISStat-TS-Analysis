"""AUTH-19 bounded SMTP delivery. Disabled by default; outage never opens entry.

Sending is a side effect outside any SQL transaction. A failed send marks the
challenge honestly (`delivery_code='failed'`) and never substitutes a fallback
that could open access without mailbox proof.
"""

import os
import smtplib
from email.message import EmailMessage

TLS_MODES = ("starttls", "ssl", "none")


class DeliveryUnavailable(Exception):
    """Any SMTP failure; safe 503 upstream, no server/secret details."""


class SmtpEmailDelivery:
    def __init__(self, *, host, port=587, user=None, password=None, sender, mode="starttls", timeout=10.0):
        if not isinstance(host, str) or not host.strip():
            raise ValueError("smtp host required")
        if mode not in TLS_MODES:
            raise ValueError("invalid tls mode")
        if not isinstance(sender, str) or not sender.strip():
            raise ValueError("smtp sender required")
        self.host = host.strip()
        self.port = int(port)
        self.user = user or None
        self.password = password or None
        self.sender = sender.strip()
        self.mode = mode
        self.timeout = float(timeout)

    def __repr__(self):
        return "SmtpEmailDelivery(host=" + self.host + ")"

    @classmethod
    def from_env(cls):
        host = os.environ.get("CISSTAT_AUTH_SMTP_HOST", "")
        if not host:
            return None
        return cls(
            host=host,
            port=os.environ.get("CISSTAT_AUTH_SMTP_PORT", "587"),
            user=os.environ.get("CISSTAT_AUTH_SMTP_USER") or None,
            password=os.environ.get("CISSTAT_AUTH_SMTP_PASSWORD") or None,
            sender=os.environ.get("CISSTAT_AUTH_SMTP_FROM", ""),
            mode=os.environ.get("CISSTAT_AUTH_SMTP_TLS", "starttls"),
        )

    def send(self, to_email, subject, body):
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        try:
            if self.mode == "ssl":
                client = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with client:
                if self.mode == "starttls":
                    client.starttls()
                if self.user:
                    client.login(self.user, self.password or "")
                client.send_message(message)
        except (smtplib.SMTPException, OSError, ValueError):
            raise DeliveryUnavailable() from None
