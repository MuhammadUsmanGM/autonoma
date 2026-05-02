"""Gmail channel — IMAP polling + SMTP reply using stdlib only."""

from __future__ import annotations

import asyncio
import email
import email.utils
import imaplib
import logging
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText

from autonoma.config import GmailConfig
from autonoma.gateway.channels.base import ChannelAdapter, MessageHandler
from autonoma.schema import Message

logger = logging.getLogger(__name__)


class GmailChannel(ChannelAdapter):
    """Gmail bot via IMAP (poll) + SMTP (reply). Uses App Password, no OAuth."""

    def __init__(self, config: GmailConfig):
        self._config = config
        self._handler: MessageHandler | None = None
        # Event-based cancellation so stop() doesn't have to wait up to
        # poll_interval seconds for an in-flight asyncio.sleep to return.
        self._stop_event: asyncio.Event | None = None

    @property
    def name(self) -> str:
        return "gmail"

    async def start(self, message_handler: MessageHandler) -> None:
        self._handler = message_handler
        # Event must be created inside the running loop — constructing it in
        # __init__ would bind it to whatever loop happens to be current at
        # import time (often none, which raises on wait()).
        self._stop_event = asyncio.Event()
        logger.info(
            "Gmail channel started (polling every %ds for %s)",
            self._config.poll_interval,
            self._config.email_address,
        )

        while not self._stop_event.is_set():
            try:
                await self._poll_inbox()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Gmail poll error: %s", e, exc_info=True)
            # Sleep OR wake early if stop() fires. wait_for raises TimeoutError
            # when poll_interval elapses without a stop signal — that's the
            # normal path through the loop.
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.poll_interval,
                )
                break  # stop_event fired: exit the loop immediately
            except asyncio.TimeoutError:
                continue  # interval elapsed: poll again

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    async def send(self, content: str) -> None:
        pass

    async def _poll_inbox(self) -> None:
        """Check for unread emails and process them."""
        emails = await asyncio.to_thread(self._fetch_unread)
        for em in emails:
            message = Message(
                channel="gmail",
                channel_id=em["message_id"],
                user_id=em["from_addr"],
                user_name=em["from_name"],
                content=em["body"],
                metadata={
                    "subject": em["subject"],
                    "headers": em.get("headers", {}),
                },
            )

            response = await self._handler(message)

            triage = (response.metadata or {}).get("triage", {})
            decision = triage.get("decision")
            if decision in {"ignore", "archive", "escalate"} or not response.content.strip():
                logger.info(
                    "Gmail reply suppressed for %s (decision=%s)",
                    em["from_addr"],
                    decision or "empty",
                )
                continue

            await asyncio.to_thread(
                self._send_reply,
                to=em["from_addr"],
                subject=f"Re: {em['subject']}",
                body=response.content,
                in_reply_to=em["message_id"],
                references=em.get("references", ""),
            )

    def _fetch_unread(self) -> list[dict]:
        """Fetch unread emails via IMAP (blocking, runs in thread)."""
        results: list[dict] = []

        conn = imaplib.IMAP4_SSL(self._config.imap_host)
        try:
            conn.login(self._config.email_address, self._config.app_password)
            conn.select("INBOX")

            _, msg_nums = conn.search(None, "UNSEEN")
            if not msg_nums[0]:
                return results

            for num in msg_nums[0].split():
                _, data = conn.fetch(num, "(RFC822)")
                if not data or not data[0]:
                    continue
                msg = email.message_from_bytes(data[0][1])

                # Extract plain text body
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="replace")
                            break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")

                # Decode subject
                raw_subject = msg.get("Subject", "")
                decoded_parts = decode_header(raw_subject)
                subject = ""
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(charset or "utf-8", errors="replace")
                    else:
                        subject += part

                from_name, from_addr = email.utils.parseaddr(msg.get("From", ""))

                results.append({
                    "message_id": msg.get("Message-ID", ""),
                    "from_addr": from_addr,
                    "from_name": from_name,
                    "subject": subject,
                    "body": body.strip(),
                    "references": msg.get("References", ""),
                    "headers": {
                        "list_unsubscribe": msg.get("List-Unsubscribe", ""),
                        "list_id": msg.get("List-Id", ""),
                        "auto_submitted": msg.get("Auto-Submitted", ""),
                        "precedence": msg.get("Precedence", ""),
                        "x_auto_response_suppress": msg.get("X-Auto-Response-Suppress", ""),
                        "return_path": msg.get("Return-Path", ""),
                        "in_reply_to": msg.get("In-Reply-To", ""),
                    },
                })

                # Mark as read
                conn.store(num, "+FLAGS", "\\Seen")

        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

        return results

    def _send_reply(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str,
        references: str,
    ) -> None:
        """Send a reply email via SMTP (blocking, runs in thread)."""
        msg = MIMEText(body)
        msg["From"] = self._config.email_address
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = f"{references} {in_reply_to}".strip()

        with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port) as server:
            server.starttls()
            server.login(self._config.email_address, self._config.app_password)
            server.send_message(msg)

        logger.info("Gmail reply sent to %s", to)
