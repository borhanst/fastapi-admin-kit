#!/usr/bin/env python3
"""Generate CHANGELOG.md from GitHub releases and tags.

This fetches the repository's releases (and, as a fallback, tags without
releases) from the GitHub REST API and (re)builds ``CHANGELOG.md``.

A manually maintained ``## [Unreleased]`` section in an existing changelog is
preserved and prepended to the generated release entries.

Usage::

    python scripts/generate_changelog.py \
        --repo borhanst/fastapi-admin-kit \
        --output CHANGELOG.md

Environment variables ``GITHUB_REPOSITORY`` and ``GITHUB_TOKEN`` are honoured
automatically when running inside GitHub Actions. A token is optional for
public repositories but raises the GitHub API rate limit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

API_ROOT = "https://api.github.com"
USER_AGENT = "fastapi-admin-kit-changelog-generator"

UNRELEASED_RE = re.compile(
    r"^##\s*\[Unreleased\].*?(?=^##\s*\[|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
HEADER_RE = re.compile(r"^.*?(?=^##\s*\[)", re.MULTILINE | re.DOTALL)


def _request(url: str, token: str | None) -> dict | list:
    """Perform a GET request against the GitHub API and return parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _all_releases(repo: str, token: str | None) -> list[dict]:
    """Return every release for the repository (handles pagination)."""
    out: list[dict] = []
    page = 1
    while True:
        url = f"{API_ROOT}/repos/{repo}/releases?per_page=100&page={page}"
        data = _request(url, token)
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < 100:
            break
        page += 1
    return out


def _all_tags(repo: str, token: str | None) -> list[dict]:
    """Return every tag for the repository (handles pagination)."""
    out: list[dict] = []
    page = 1
    while True:
        url = f"{API_ROOT}/repos/{repo}/tags?per_page=100&page={page}"
        data = _request(url, token)
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < 100:
            break
        page += 1
    return out


def _tag_commit_date(repo: str, sha: str, token: str | None) -> str | None:
    """Best-effort commit date for a tag that has no associated release."""
    try:
        commit = _request(f"{API_ROOT}/repos/{repo}/commits/{sha}", token)
        return commit.get("commit", {}).get("committer", {}).get("date")
    except urllib.error.HTTPError:
        return None


def _fmt_date(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(UTC).strftime("%Y-%m-%d")
    except ValueError:
        return value[:10]


def _clean_version(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def _is_version_tag(tag: str) -> bool:
    return re.fullmatch(r"v?\d+\.\d+\.\d+", tag.strip()) is not None


_PR_LINE_RE = re.compile(r"^\*\s+(?P<title>.+?)\s+by\s+@\w+\s+in\s+(?P<url>https?://\S+)\s*$")
_FULL_CHANGELOG_RE = re.compile(r"^\*\*Full Changelog\*\*.*$", re.MULTILINE)
_WHATS_CHANGED_RE = re.compile(r"^##\s+What's Changed\s*$", re.MULTILINE | re.IGNORECASE)


def _humanize_pr_line(line: str) -> str | None:
    """Convert a raw GitHub ``* title by @user in URL`` line into markdown.

    Returns the cleaned bullet (e.g. ``* title ([#39](url))``) or ``None`` when
    the line does not match the PR format.
    """
    match = _PR_LINE_RE.match(line)
    if not match:
        return None
    title = match.group("title").rstrip().rstrip(".")
    url = match.group("url")
    pr_number = url.rstrip("/").rsplit("/")[-1]
    return f"- {title} ([#{pr_number}]({url}))"


def _normalize_body(body: str | None) -> str:
    """Turn a raw GitHub release body into clean, human-readable markdown.

    Strips the ``**Full Changelog**`` footer and the ``## What's Changed``
    subheading, and rewrites PR bullet lines into readable ``- title ([#n](url))``
    form.
    """
    if not body:
        return "_No release notes provided._"
    body = _FULL_CHANGELOG_RE.sub("", body)
    body = _WHATS_CHANGED_RE.sub("", body)

    cleaned: list[str] = []
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip() and not cleaned:
            continue
        human = _humanize_pr_line(line)
        if human is not None:
            cleaned.append(human)
        elif line.strip():
            cleaned.append(line)
    text = "\n".join(cleaned).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text or "_No release notes provided._"


def build_release_entries(repo: str, token: str | None) -> list[str]:
    """Build changelog sections for each published release, newest first."""
    sections: list[str] = []
    seen_tags: set[str] = set()

    for rel in _all_releases(repo, token):
        tag = rel.get("tag_name") or ""
        if not tag:
            continue
        seen_tags.add(tag)
        date = _fmt_date(rel.get("published_at"))
        version = _clean_version(tag)
        title = f"## [{version}] - {date}"
        body = _normalize_body(rel.get("body"))
        sections.append(f"{title}\n\n{body}\n")

    # Fall back to tags that have no release object.
    for tag in _all_tags(repo, token):
        name = tag.get("name") or tag.get("commit", {}).get("sha", "")
        if not _is_version_tag(name) or name in seen_tags:
            continue
        sha = tag.get("commit", {}).get("sha")
        date = _fmt_date(_tag_commit_date(repo, sha, token)) if sha else "unknown"
        version = _clean_version(name)
        title = f"## [{version}] - {date}"
        sections.append(f"{title}\n\n_Generated from tag `{name}` (no release notes)._\n")

    return sections


def extract_unreleased(existing: str) -> str:
    """Extract a manual ``## [Unreleased]`` block, if present."""
    match = UNRELEASED_RE.search(existing)
    if not match:
        return ""
    block = match.group(0).strip()
    return block + "\n"


def extract_header(existing: str) -> str:
    """Extract the leading header (everything before the first version heading)."""
    match = HEADER_RE.search(existing)
    if not match:
        return (
            "# Changelog\n\n"
            "All notable changes to this project will be documented in this file.\n\n"
            "The format is based on [Keep a Changelog]"
            "(https://keepachangelog.com/en/1.1.0/),\n"
            "and this project adheres to "
            "[Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n"
        )
    return match.group(0).rstrip() + "\n"


def generate(repo: str, token: str | None, output_path: str) -> str:
    existing = ""
    if os.path.isfile(output_path):
        with open(output_path, encoding="utf-8") as fh:
            existing = fh.read()

    header = extract_header(existing)
    unreleased = extract_unreleased(existing)
    entries = build_release_entries(repo, token)

    parts = [header, "\n"]
    if unreleased:
        parts.append(unreleased + "\n")
    if entries:
        parts.append("\n".join(entries) + "\n")
    else:
        parts.append(
            "## [0.0.0] - " + datetime.now(UTC).strftime("%Y-%m-%d") + "\n\n"
            "_No releases or tags found yet._\n"
        )

    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", "borhanst/fastapi-admin-kit"),
        help="owner/name of the GitHub repository",
    )
    parser.add_argument(
        "--output",
        default="CHANGELOG.md",
        help="path to write the generated changelog",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="optional GitHub token (raises API rate limit)",
    )
    args = parser.parse_args(argv)

    if args.repo.count("/") != 1:
        print(f"error: invalid repo '{args.repo}' (expected owner/name)", file=sys.stderr)
        return 2

    try:
        content = generate(args.repo, args.token, args.output)
    except urllib.error.HTTPError as exc:
        print(f"error: GitHub API request failed: {exc}", file=sys.stderr)
        return 1

    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"Wrote changelog for {args.repo} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
