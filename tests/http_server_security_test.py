import asyncio
import unittest

from autonoma.gateway.channels._http_server import (
    MAX_REQUEST_BYTES,
    HTTPServer,
    _RequestTooLarge,
    _record_webhook,
    webhook_buffer,
)


class HTTPRequestLimitTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_oversized_content_length(self) -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(
            f"POST /api/chat HTTP/1.1\r\nContent-Length: {MAX_REQUEST_BYTES + 1}\r\n\r\n".encode()
        )
        reader.feed_eof()

        with self.assertRaises(_RequestTooLarge):
            await HTTPServer()._read_request(reader)


class WebhookCapturePrivacyTest(unittest.TestCase):
    def setUp(self) -> None:
        webhook_buffer.clear()

    def tearDown(self) -> None:
        webhook_buffer.clear()

    def test_capture_redacts_headers_and_does_not_keep_payload(self) -> None:
        _record_webhook({
            "method": "POST",
            "path": "/webhook/whatsapp?token=private",
            "headers": {
                "authorization": "Bearer private",
                "Cookie": "session=private",
                "content-type": "application/json",
            },
            "body": '{"body":"private message"}',
            "json": {"body": "private message"},
        })

        entry = webhook_buffer[0]
        self.assertEqual(entry["path"], "/webhook/whatsapp")
        self.assertEqual(entry["headers"]["authorization"], "[REDACTED]")
        self.assertEqual(entry["headers"]["Cookie"], "[REDACTED]")
        self.assertEqual(entry["body"], "")
        self.assertEqual(entry["json"], {})
        self.assertFalse(entry["body_captured"])

    def test_chat_requests_are_not_captured(self) -> None:
        _record_webhook({
            "method": "POST",
            "path": "/api/chat",
            "headers": {},
            "body": '{"message":"private"}',
            "json": {"message": "private"},
        })

        self.assertEqual(webhook_buffer, [])