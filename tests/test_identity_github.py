"""Tests for the github identifier kind in identity extraction."""

from __future__ import annotations

import unittest

from autonoma.cortex.identity import (
    KIND_EMAIL,
    KIND_GITHUB,
    classify_user_id,
    extract_github_logins,
    extract_identifiers_for_channel,
    normalize_github_login,
    parse_link_identity_tags,
)


class NormalizeGithubLoginTest(unittest.TestCase):
    def test_valid_logins(self) -> None:
        for ok in ("Octocat", "octocat", "a1-b2", "torvalds", "a"):
            self.assertEqual(normalize_github_login(ok), ok.lower(), ok)

    def test_strips_at_prefix(self) -> None:
        self.assertEqual(normalize_github_login("@OctoCat"), "octocat")

    def test_invalid_logins(self) -> None:
        for bad in ("-alice", "alice-", "a--b", "a_b", "", "  ",
                    "a" * 40, "ali ce"):
            self.assertIsNone(normalize_github_login(bad), bad)


class ExtractGithubLoginsTest(unittest.TestCase):
    def test_extracts_simple_mention(self) -> None:
        idents = extract_github_logins("hi @octocat please review")
        self.assertEqual([(i.kind, i.value) for i in idents],
                         [(KIND_GITHUB, "octocat")])

    def test_skips_emails(self) -> None:
        # "@example" inside an email must not be extracted.
        self.assertEqual(extract_github_logins("ping alice@example.com"), [])

    def test_skips_repo_path(self) -> None:
        self.assertEqual(extract_github_logins("see github.com/owner/repo"), [])

    def test_dedupes_repeated_mentions(self) -> None:
        idents = extract_github_logins("@octocat @OctoCat @octocat")
        self.assertEqual(len(idents), 1)


class ChannelAwareExtractionTest(unittest.TestCase):
    def test_github_channel_includes_logins(self) -> None:
        idents = extract_identifiers_for_channel(
            "github", "ping @octocat about the bug"
        )
        kinds = [i.kind for i in idents]
        self.assertIn(KIND_GITHUB, kinds)

    def test_other_channels_skip_logins(self) -> None:
        idents = extract_identifiers_for_channel(
            "telegram", "ping @octocat about the bug"
        )
        for ident in idents:
            self.assertNotEqual(ident.kind, KIND_GITHUB)

    def test_emails_still_picked_up(self) -> None:
        idents = extract_identifiers_for_channel(
            "github", "Email me at alice@example.com — also @octocat"
        )
        kinds = {i.kind for i in idents}
        self.assertIn(KIND_EMAIL, kinds)
        self.assertIn(KIND_GITHUB, kinds)


class ClassifyAndLinkTagTest(unittest.TestCase):
    def test_github_channel_classifies_as_github_kind(self) -> None:
        ident = classify_user_id("github", "Octocat")
        self.assertEqual(ident.kind, KIND_GITHUB)
        self.assertEqual(ident.value, "octocat")

    def test_link_identity_tag_for_github(self) -> None:
        idents, cleaned = parse_link_identity_tags(
            "Got it [LINK_IDENTITY: github=Octocat] thanks"
        )
        self.assertEqual([(i.kind, i.value) for i in idents],
                         [(KIND_GITHUB, "octocat")])
        self.assertNotIn("LINK_IDENTITY", cleaned)


if __name__ == "__main__":
    unittest.main()
