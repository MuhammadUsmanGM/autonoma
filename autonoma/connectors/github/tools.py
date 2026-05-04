"""Tools backed by the GitHub connector (REST API v2022-11-28)."""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

from autonoma.connectors.oauth import http_json
from autonoma.executor.tools.base import BaseTool, ToolPermission

if TYPE_CHECKING:
    from autonoma.connectors.github.connector import GitHubConnector

API_BASE = "https://api.github.com"

# GitHub repos: owner is alphanumeric+hyphen (no leading hyphen, no double),
# name is alphanumeric + ".-_". This regex blocks leading slashes, query
# strings, and absolute URLs that would otherwise leak through into the
# API path and cause SSRF-like requests against unintended endpoints.
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")


def _validate_repo(repo: str) -> str:
    repo = repo.strip().strip("/")
    if not _REPO_RE.match(repo):
        raise ValueError(
            f"Invalid repo {repo!r}; expected 'owner/name' with GitHub-allowed chars."
        )
    return repo


def _perm() -> ToolPermission:
    return ToolPermission(
        level="cautious",
        network=True,
        external_api=True,
        secrets=True,
        description="Calls the GitHub REST API on behalf of a connected account.",
    )


def _write_perm() -> ToolPermission:
    return ToolPermission(
        level="dangerous",
        network=True,
        external_api=True,
        secrets=True,
        description="Mutates GitHub state (comment / create issue) on behalf of a connected account.",
    )


def _to_thread(fn, *args, **kwargs):
    return asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


def _gh_get(url: str, token: str, params: dict[str, Any] | None = None) -> Any:
    return http_json(url, bearer=token, params=params)


def _gh_post(url: str, token: str, body: dict[str, Any]) -> Any:
    return http_json(url, method="POST", bearer=token, body=body)


class _BaseGitHubTool(BaseTool):
    def __init__(self, connector: "GitHubConnector") -> None:
        self._connector = connector


class GitHubSearchIssuesTool(_BaseGitHubTool):
    @property
    def name(self) -> str:
        return "github_search_issues"

    @property
    def description(self) -> str:
        return (
            "Search GitHub issues and pull requests using the search API. "
            "Returns up to 20 matches with title, state, and URL."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'is:open label:bug repo:owner/name'",
                },
                "repo": {
                    "type": "string",
                    "description": "Optional 'owner/name' to scope the query (added as repo:owner/name).",
                },
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "default": "open",
                },
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        q = params["query"].strip()
        if repo := params.get("repo"):
            repo = _validate_repo(repo)
            q = f"{q} repo:{repo}"
        state = params.get("state", "open")
        if state in ("open", "closed"):
            q = f"{q} state:{state}"
        limit = max(1, min(int(params.get("limit", 20)), 50))
        token = self._connector.access_token()
        resp = await _to_thread(
            _gh_get,
            f"{API_BASE}/search/issues",
            token,
            {"q": q, "per_page": limit},
        )
        items = resp.get("items", []) or []
        if not items:
            return f"No issues match: {q}"
        lines = [f"{resp.get('total_count', len(items))} total match(es) for {q!r}:"]
        for it in items[:limit]:
            kind = "PR  " if "pull_request" in it else "ISS "
            lines.append(
                f"- {kind} #{it.get('number')} [{it.get('state','?')}] "
                f"{it.get('title','(no title)')}\n  {it.get('html_url','')}"
            )
        return "\n".join(lines)


class GitHubGetIssueTool(_BaseGitHubTool):
    @property
    def name(self) -> str:
        return "github_get_issue"

    @property
    def description(self) -> str:
        return "Fetch a single issue's title, body, state, labels, and recent comments."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/name"},
                "number": {"type": "integer", "minimum": 1},
                "comments": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 0,
                    "maximum": 20,
                    "description": "How many recent comments to include.",
                },
            },
            "required": ["repo", "number"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        repo = _validate_repo(params["repo"])
        number = int(params["number"])
        token = self._connector.access_token()
        issue = await _to_thread(
            _gh_get, f"{API_BASE}/repos/{repo}/issues/{number}", token
        )
        labels = ", ".join(l.get("name", "") for l in issue.get("labels", []) or [])
        body = (issue.get("body") or "").strip()
        if len(body) > 1500:
            body = body[:1500] + "…"
        out = [
            f"#{issue.get('number')} {issue.get('title','(no title)')}",
            f"state={issue.get('state','?')}  by={issue.get('user',{}).get('login','?')}  labels=[{labels}]",
            f"url={issue.get('html_url','')}",
            "",
            body or "(no body)",
        ]
        n_comments = max(0, min(int(params.get("comments", 5)), 20))
        if n_comments and (issue.get("comments") or 0) > 0:
            comments = await _to_thread(
                _gh_get,
                f"{API_BASE}/repos/{repo}/issues/{number}/comments",
                token,
                {"per_page": n_comments, "sort": "created", "direction": "desc"},
            )
            out.append("")
            out.append(f"Recent comments ({len(comments)}):")
            for c in (comments or [])[:n_comments]:
                snippet = (c.get("body") or "").strip().replace("\r", "")
                if len(snippet) > 300:
                    snippet = snippet[:300] + "…"
                out.append(f"- @{c.get('user',{}).get('login','?')}: {snippet}")
        return "\n".join(out)


class GitHubGetPRTool(_BaseGitHubTool):
    @property
    def name(self) -> str:
        return "github_get_pr"

    @property
    def description(self) -> str:
        return "Fetch a pull request with status, changed files summary, and recent reviews."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/name"},
                "number": {"type": "integer", "minimum": 1},
            },
            "required": ["repo", "number"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        repo = _validate_repo(params["repo"])
        number = int(params["number"])
        token = self._connector.access_token()
        pr = await _to_thread(
            _gh_get, f"{API_BASE}/repos/{repo}/pulls/{number}", token
        )
        body = (pr.get("body") or "").strip()
        if len(body) > 1200:
            body = body[:1200] + "…"
        out = [
            f"PR #{pr.get('number')} {pr.get('title','(no title)')}",
            f"state={pr.get('state','?')}  draft={pr.get('draft', False)}  "
            f"merged={pr.get('merged', False)}  by={pr.get('user',{}).get('login','?')}",
            f"base={pr.get('base',{}).get('ref','?')}  head={pr.get('head',{}).get('ref','?')}",
            f"+{pr.get('additions',0)} / -{pr.get('deletions',0)}  "
            f"files={pr.get('changed_files',0)}",
            f"url={pr.get('html_url','')}",
            "",
            body or "(no description)",
        ]
        # Files (top 10) and reviews are best-effort — a 404/403 on either
        # shouldn't blank out the whole tool result.
        try:
            files = await _to_thread(
                _gh_get,
                f"{API_BASE}/repos/{repo}/pulls/{number}/files",
                token,
                {"per_page": 10},
            )
            if files:
                out.append("")
                out.append(f"Changed files (top {min(len(files), 10)}):")
                for f in files[:10]:
                    out.append(
                        f"- {f.get('status','?'):>8}  "
                        f"{f.get('filename','?')}  "
                        f"(+{f.get('additions',0)}/-{f.get('deletions',0)})"
                    )
        except Exception:
            pass
        try:
            reviews = await _to_thread(
                _gh_get,
                f"{API_BASE}/repos/{repo}/pulls/{number}/reviews",
                token,
                {"per_page": 10},
            )
            if reviews:
                out.append("")
                out.append(f"Reviews ({len(reviews)}):")
                for r in reviews[-10:]:
                    out.append(
                        f"- @{r.get('user',{}).get('login','?')} "
                        f"{r.get('state','?')}: "
                        f"{(r.get('body') or '').strip()[:120]}"
                    )
        except Exception:
            pass
        return "\n".join(out)


class GitHubListNotificationsTool(_BaseGitHubTool):
    @property
    def name(self) -> str:
        return "github_list_notifications"

    @property
    def description(self) -> str:
        return "List the user's GitHub notifications (issues, PRs, mentions, reviews)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unread_only": {"type": "boolean", "default": True},
                "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            },
        }

    @property
    def permissions(self) -> ToolPermission:
        return _perm()

    async def execute(self, params: dict[str, Any]) -> str:
        token = self._connector.access_token()
        unread_only = bool(params.get("unread_only", True))
        limit = max(1, min(int(params.get("limit", 25)), 100))
        notes = await _to_thread(
            _gh_get,
            f"{API_BASE}/notifications",
            token,
            {"all": "false" if unread_only else "true", "per_page": limit},
        )
        if not notes:
            return "(no notifications)" if not unread_only else "(no unread notifications)"
        lines = [f"{len(notes)} notification(s):"]
        for n in notes:
            subject = n.get("subject", {}) or {}
            repo = (n.get("repository", {}) or {}).get("full_name", "?")
            lines.append(
                f"- {subject.get('type','?'):<11} {repo}  "
                f"{subject.get('title','?')}  "
                f"reason={n.get('reason','?')}"
            )
        return "\n".join(lines)


class GitHubCommentTool(_BaseGitHubTool):
    @property
    def name(self) -> str:
        return "github_comment"

    @property
    def description(self) -> str:
        return "Post a comment on a GitHub issue or pull request."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/name"},
                "number": {"type": "integer", "minimum": 1},
                "body": {"type": "string", "minLength": 1, "maxLength": 65536},
            },
            "required": ["repo", "number", "body"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _write_perm()

    async def execute(self, params: dict[str, Any]) -> str:
        repo = _validate_repo(params["repo"])
        number = int(params["number"])
        body = params["body"].strip()
        if not body:
            raise ValueError("Comment body must not be empty.")
        token = self._connector.access_token()
        resp = await _to_thread(
            _gh_post,
            f"{API_BASE}/repos/{repo}/issues/{number}/comments",
            token,
            {"body": body},
        )
        return f"Posted comment {resp.get('id','?')} on {repo}#{number}: {resp.get('html_url','')}"


class GitHubCreateIssueTool(_BaseGitHubTool):
    @property
    def name(self) -> str:
        return "github_create_issue"

    @property
    def description(self) -> str:
        return "Open a new issue in a GitHub repository."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/name"},
                "title": {"type": "string", "minLength": 1, "maxLength": 256},
                "body": {"type": "string", "default": ""},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
            },
            "required": ["repo", "title"],
        }

    @property
    def permissions(self) -> ToolPermission:
        return _write_perm()

    async def execute(self, params: dict[str, Any]) -> str:
        repo = _validate_repo(params["repo"])
        title = params["title"].strip()
        if not title:
            raise ValueError("Issue title must not be empty.")
        token = self._connector.access_token()
        body: dict[str, Any] = {"title": title, "body": params.get("body", "")}
        if labels := params.get("labels"):
            body["labels"] = [str(l) for l in labels]
        resp = await _to_thread(
            _gh_post, f"{API_BASE}/repos/{repo}/issues", token, body
        )
        return f"Opened issue #{resp.get('number','?')} in {repo}: {resp.get('html_url','')}"
