import unittest

from autonoma.gateway.channels.connectors_api import _callback_page


class OAuthCallbackHTMLTest(unittest.TestCase):
    def test_escapes_untrusted_html_text(self) -> None:
        page = _callback_page(
            "Authorization denied",
            '</p><script>alert("x")</script>',
            "google_calendar",
            "error",
        )

        self.assertIn("&lt;/p&gt;&lt;script&gt;", page)
        self.assertNotIn('</p><script>alert("x")</script>', page)

    def test_json_script_values_cannot_close_script_element(self) -> None:
        page = _callback_page("Done", "OK", "</script>", "connected")

        self.assertIn(r"\u003c/script>", page)
        self.assertNotIn('name: "</script>"', page)