"""GitHub connector tool tests — mock http_json, no network."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from autonoma.connectors.github import tools as gh_tools


def _run(coro):
    return asyncio.run(coro)


class _FakeConnector:
    def __init__(self, token: str = "tok") -> None:
        self._token = token

    def access_token(self) -> str:
        return self._token


class RepoValidationTest(unittest.TestCase):
    def test_validates_owner_repo(self) -> None:
        self.assertEqual(gh_tools._validate_repo("octo/Hello-World"), "octo/Hello-World")
        self.assertEqual(gh_tools._validate_repo(" /octo/foo/ "), "octo/foo")

    def test_rejects_traversal_and_garbage(self) -> None:
        for bad in ("../etc/passwd", "owner", "owner/",
                    "ow ner/foo", "owner/foo?x=1", "-bad/foo"):
            with self.assertRaises(ValueError):
                gh_tools._validate_repo(bad)


class SearchIssuesTest(unittest.TestCase):
    def test_appends_repo_and_state(self) -> None:
        captured: dict = {}

        def fake(url, bearer=None, params=None, **_):
            captured["url"] = url
            captured["params"] = params
            return {
                "total_count": 2,
                "items": [
                    {"number": 1, "state": "open", "title": "bug",
                     "html_url": "u1"},
                    {"number": 2, "state": "open", "title": "feat",
                     "html_url": "u2", "pull_request": {}},
                ],
            }

        tool = gh_tools.GitHubSearchIssuesTool(_FakeConnector())
        with patch.object(gh_tools, "http_json", side_effect=fake):
            out = _run(tool.execute({
                "query": "label:bug", "repo": "octo/foo", "state": "open",
            }))
        self.assertIn("repo:octo/foo", captured["params"]["q"])
        self.assertIn("state:open", captured["params"]["q"])
        self.assertIn("ISS  #1", out)
        self.assertIn("PR   #2", out)


class CommentTest(unittest.TestCase):
    def test_posts_comment(self) -> None:
        seen: dict = {}

        def fake(url, method=None, bearer=None, body=None, **_):
            seen["method"] = method
            seen["url"] = url
            seen["body"] = body
            return {"id": 99, "html_url": "https://x/99"}

        tool = gh_tools.GitHubCommentTool(_FakeConnector())
        with patch.object(gh_tools, "http_json", side_effect=fake):
            out = _run(tool.execute({
                "repo": "octo/foo", "number": 7, "body": "ack",
            }))
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["body"], {"body": "ack"})
        self.assertIn("octo/foo#7", out)

    def test_rejects_blank_body(self) -> None:
        tool = gh_tools.GitHubCommentTool(_FakeConnector())
        with self.assertRaises(ValueError):
            _run(tool.execute({"repo": "o/f", "number": 1, "body": "   "}))


class CreateIssueTest(unittest.TestCase):
    def test_creates_with_labels(self) -> None:
        seen: dict = {}

        def fake(url, method=None, bearer=None, body=None, **_):
            seen["body"] = body
            return {"number": 42, "html_url": "https://x/42"}

        tool = gh_tools.GitHubCreateIssueTool(_FakeConnector())
        with patch.object(gh_tools, "http_json", side_effect=fake):
            out = _run(tool.execute({
                "repo": "octo/foo", "title": "T", "body": "B",
                "labels": ["bug", "p1"],
            }))
        self.assertEqual(seen["body"]["labels"], ["bug", "p1"])
        self.assertIn("#42", out)


if __name__ == "__main__":
    unittest.main()
