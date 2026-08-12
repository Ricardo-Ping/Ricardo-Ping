#!/usr/bin/env python3
"""Generate static SVG cards for the GitHub profile README."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


API_BASE = "https://api.github.com"
ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
USER_AGENT = "Ricardo-Ping-profile-stats-generator"
FONT_STACK = "Segoe UI, Helvetica, Arial, sans-serif"

CARD_BG = "#0d1117"
CARD_SURFACE = "#111826"
CARD_SURFACE_ALT = "#161b22"
CARD_BORDER = "#2f3746"
TEXT_PRIMARY = "#f8fafc"
TEXT_MUTED = "#94a3b8"
TEXT_SOFT = "#64748b"
ACCENT = "#58a6ff"
ACCENT_DEEP = "#1f6feb"
BAR_BG = "#202938"

LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "Jupyter Notebook": "#DA5B0B",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Java": "#b07219",
    "C++": "#f34b7d",
    "C": "#555555",
    "Shell": "#89e051",
    "PowerShell": "#012456",
    "MATLAB": "#e16737",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Vue": "#41b883",
    "TeX": "#3d6117",
}


def github_request(url: str, token: str | None) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            headers = {key.lower(): value for key, value in response.headers.items()}
            return payload, headers
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API request failed for {url}: HTTP {exc.code} {details}"
        ) from exc


def fetch_user(username: str, token: str | None) -> dict[str, Any]:
    payload, _ = github_request(f"{API_BASE}/users/{urllib.parse.quote(username)}", token)
    return payload


def fetch_repositories(username: str, token: str | None) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1
    while True:
        url = (
            f"{API_BASE}/users/{urllib.parse.quote(username)}/repos"
            f"?per_page=100&type=owner&sort=updated&page={page}"
        )
        payload, _ = github_request(url, token)
        if not payload:
            break
        repositories.extend(payload)
        if len(payload) < 100:
            break
        page += 1
    return repositories


def fetch_languages(url: str, token: str | None) -> dict[str, int]:
    payload, _ = github_request(url, token)
    return {name: int(size) for name, size in payload.items()}


def resolve_token() -> str | None:
    direct_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if direct_token:
        return direct_token

    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if gh_token:
        return gh_token

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None

    token = result.stdout.strip()
    return token or None


def format_number(value: int) -> str:
    return f"{value:,}"


def format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"

    units = ["KB", "MB", "GB", "TB"]
    scaled = float(value)
    for unit in units:
        scaled /= 1024.0
        if scaled < 1024.0 or unit == units[-1]:
            if scaled >= 100:
                return f"{scaled:.0f} {unit}"
            if scaled >= 10:
                return f"{scaled:.1f} {unit}"
            return f"{scaled:.2f} {unit}"
    return f"{value} B"


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def defs_block() -> str:
    return f"""
  <defs>
    <linearGradient id="cardAccent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{ACCENT}" />
      <stop offset="100%" stop-color="{ACCENT_DEEP}" />
    </linearGradient>
    <linearGradient id="heroGlow" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#111827" />
    </linearGradient>
  </defs>"""


def label_chip(x: int, y: int, width: int, text: str) -> str:
    safe_text = escape(text)
    return f"""
  <g transform="translate({x},{y})">
    <rect width="{width}" height="30" rx="15" fill="{CARD_SURFACE_ALT}" stroke="{CARD_BORDER}" />
    <circle cx="16" cy="15" r="4" fill="{ACCENT}" />
    <text x="28" y="19" font-family="{FONT_STACK}" font-size="12" fill="{TEXT_MUTED}">{safe_text}</text>
  </g>"""


def metric_icon(kind: str, x: int, y: int, color: str) -> str:
    parts = [
        f'<g transform="translate({x},{y})">',
        f'<rect width="44" height="44" rx="14" fill="#0f1722" stroke="{CARD_BORDER}" />',
    ]

    if kind == "repos":
        parts.extend(
            [
                f'<rect x="13" y="12" width="18" height="20" rx="3" fill="none" stroke="{color}" stroke-width="2" />',
                f'<line x1="16" y1="17" x2="28" y2="17" stroke="{color}" stroke-width="2" />',
                f'<line x1="16" y1="22" x2="28" y2="22" stroke="{color}" stroke-width="2" />',
            ]
        )
    elif kind == "followers":
        parts.extend(
            [
                f'<circle cx="22" cy="17" r="7" fill="none" stroke="{color}" stroke-width="2" />',
                f'<path d="M13 32c2.7-5.6 14.3-5.6 18 0" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" />',
            ]
        )
    elif kind == "stars":
        parts.append(
            f'<path d="M22 10l3.6 7.3 8 1.2-5.8 5.6 1.4 8-7.2-3.8-7.2 3.8 1.4-8-5.8-5.6 8-1.2L22 10z" fill="{color}" />'
        )
    elif kind == "forks":
        parts.extend(
            [
                f'<circle cx="15" cy="14" r="4" fill="none" stroke="{color}" stroke-width="2" />',
                f'<circle cx="29" cy="14" r="4" fill="none" stroke="{color}" stroke-width="2" />',
                f'<circle cx="22" cy="31" r="4" fill="none" stroke="{color}" stroke-width="2" />',
                f'<line x1="17.8" y1="17.2" x2="20.2" y2="27.8" stroke="{color}" stroke-width="2" />',
                f'<line x1="26.2" y1="17.2" x2="23.8" y2="27.8" stroke="{color}" stroke-width="2" />',
            ]
        )

    parts.append("</g>")
    return "\n".join(parts)


def metric_card(
    x: int,
    y: int,
    title: str,
    value: str,
    description: str,
    kind: str,
    color: str,
) -> str:
    safe_title = escape(title)
    safe_value = escape(value)
    safe_description = escape(description)
    return f"""
  <g transform="translate({x},{y})">
    <rect width="360" height="94" rx="20" fill="{CARD_SURFACE}" stroke="{CARD_BORDER}" />
    <rect x="0" y="0" width="360" height="5" rx="20" fill="url(#cardAccent)" opacity="0.9" />
    <text x="22" y="33" font-family="{FONT_STACK}" font-size="14" fill="{TEXT_MUTED}">{safe_title}</text>
    <text x="22" y="66" font-family="{FONT_STACK}" font-size="30" font-weight="700" fill="{TEXT_PRIMARY}">{safe_value}</text>
    <text x="22" y="82" font-family="{FONT_STACK}" font-size="12" fill="{TEXT_SOFT}">{safe_description}</text>
{metric_icon(kind, 294, 24, color)}
  </g>"""


def render_stats_svg(username: str, stats: dict[str, int], generated_at: str) -> str:
    safe_username = escape(username)
    return f"""<svg width="820" height="336" viewBox="0 0 820 336" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="statsTitle statsDesc">
{defs_block()}
  <title id="statsTitle">{safe_username} GitHub Stats</title>
  <desc id="statsDesc">Auto-generated GitHub profile statistics card.</desc>
  <rect x="1" y="1" width="818" height="334" rx="24" fill="{CARD_BG}" stroke="{CARD_BORDER}" />
  <rect x="1" y="1" width="818" height="10" rx="24" fill="url(#cardAccent)" />
  <rect x="24" y="24" width="772" height="84" rx="22" fill="url(#heroGlow)" stroke="{CARD_BORDER}" />
  <text x="40" y="58" font-family="{FONT_STACK}" font-size="29" font-weight="700" fill="{TEXT_PRIMARY}">GitHub Stats</text>
  <text x="40" y="84" font-family="{FONT_STACK}" font-size="14" fill="{TEXT_MUTED}">@{safe_username} - public activity snapshot</text>
{label_chip(574, 40, 206, f"Updated {generated_at} UTC")}
  <text x="40" y="104" font-family="{FONT_STACK}" font-size="12" fill="{TEXT_SOFT}">Static cards generated from the GitHub API for a stable profile README.</text>
{metric_card(32, 128, "Public repositories", format_number(stats["public_repos"]), "Owned public repositories on GitHub", "repos", ACCENT)}
{metric_card(396, 128, "Followers", format_number(stats["followers"]), "People following this profile", "followers", "#76a9fa")}
{metric_card(32, 232, "Total stars", format_number(stats["stars"]), "Stars across owned non-fork repositories", "stars", "#fbbf24")}
{metric_card(396, 232, "Total forks", format_number(stats["forks"]), "Forks across owned non-fork repositories", "forks", "#34d399")}
</svg>
"""


def render_language_row(
    language: str, size: int, total: int, index: int, total_width: int
) -> str:
    percent = (size / total * 100) if total else 0.0
    color = LANGUAGE_COLORS.get(language, ACCENT)
    y = 124 + index * 64
    bar_width = max(18, int(round(total_width * percent / 100))) if percent > 0 else 0
    safe_language = escape(truncate(language, 24))
    separator = ""
    if index > 0:
        separator = f'    <line x1="0" y1="-18" x2="748" y2="-18" stroke="{CARD_BORDER}" opacity="0.55" />\n'
    return f"""  <g transform="translate(36,{y})">
{separator}    <circle cx="8" cy="11" r="7" fill="{color}" />
    <text x="28" y="16" font-family="{FONT_STACK}" font-size="18" font-weight="600" fill="{TEXT_PRIMARY}">{safe_language}</text>
    <text x="748" y="16" text-anchor="end" font-family="{FONT_STACK}" font-size="18" font-weight="600" fill="{TEXT_PRIMARY}">{percent:.1f}%</text>
    <rect x="28" y="30" width="{total_width}" height="10" rx="5" fill="{BAR_BG}" />
    <rect x="28" y="30" width="{bar_width}" height="10" rx="5" fill="{color}" />
    <text x="28" y="56" font-family="{FONT_STACK}" font-size="12" fill="{TEXT_SOFT}">{format_bytes(size)} of tracked source</text>
    <text x="748" y="56" text-anchor="end" font-family="{FONT_STACK}" font-size="12" fill="{TEXT_MUTED}">{format_number(size)} bytes</text>
  </g>"""


def render_languages_svg(
    username: str,
    languages: list[tuple[str, int]],
    generated_at: str,
    repo_count: int,
) -> str:
    safe_username = escape(username)
    total_bytes = sum(size for _, size in languages)
    rows: list[str] = []

    if total_bytes == 0:
        rows.append(
            f'  <text x="36" y="144" font-family="{FONT_STACK}" font-size="16" fill="{TEXT_MUTED}">No language data available yet.</text>'
        )
        content_height = 188
    else:
        top_languages = languages[:6]
        for index, (language, size) in enumerate(top_languages):
            rows.append(render_language_row(language, size, total_bytes, index, 560))
        content_height = 120 + len(top_languages) * 64 + 20

    total_height = max(236, content_height + 24)
    rows_markup = "\n".join(rows)
    return f"""<svg width="820" height="{total_height}" viewBox="0 0 820 {total_height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="langsTitle langsDesc">
{defs_block()}
  <title id="langsTitle">{safe_username} Top Languages</title>
  <desc id="langsDesc">Auto-generated GitHub profile language distribution card.</desc>
  <rect x="1" y="1" width="818" height="{total_height - 2}" rx="24" fill="{CARD_BG}" stroke="{CARD_BORDER}" />
  <rect x="1" y="1" width="818" height="10" rx="24" fill="url(#cardAccent)" />
  <text x="36" y="54" font-family="{FONT_STACK}" font-size="29" font-weight="700" fill="{TEXT_PRIMARY}">Top Languages</text>
  <text x="36" y="82" font-family="{FONT_STACK}" font-size="14" fill="{TEXT_MUTED}">@{safe_username} - aggregated from {repo_count} owned public repositories</text>
{label_chip(582, 34, 198, f"Updated {generated_at} UTC")}
  <g transform="translate(36,94)">
    <rect width="230" height="26" rx="13" fill="{CARD_SURFACE_ALT}" stroke="{CARD_BORDER}" />
    <text x="14" y="17" font-family="{FONT_STACK}" font-size="12" fill="{TEXT_MUTED}">{len(languages[:6])} languages shown</text>
  </g>
  <g transform="translate(276,94)">
    <rect width="182" height="26" rx="13" fill="{CARD_SURFACE_ALT}" stroke="{CARD_BORDER}" />
    <text x="14" y="17" font-family="{FONT_STACK}" font-size="12" fill="{TEXT_MUTED}">{format_bytes(total_bytes)} tracked total</text>
  </g>
{rows_markup}
</svg>
"""


def main() -> int:
    username = os.environ.get("GITHUB_USERNAME", "Ricardo-Ping").strip()
    token = resolve_token()

    if not username:
        raise RuntimeError("GITHUB_USERNAME must not be empty.")

    user = fetch_user(username, token)
    repositories = fetch_repositories(username, token)
    owned_non_fork_repos = [repo for repo in repositories if not repo.get("fork")]

    total_stars = sum(int(repo.get("stargazers_count", 0)) for repo in owned_non_fork_repos)
    total_forks = sum(int(repo.get("forks_count", 0)) for repo in owned_non_fork_repos)

    language_totals: Counter[str] = Counter()
    for repository in owned_non_fork_repos:
        languages_url = repository.get("languages_url")
        if not languages_url:
            continue
        try:
            language_totals.update(fetch_languages(languages_url, token))
        except RuntimeError as exc:
            print(
                f"warning: skipped languages for {repository.get('name', 'unknown repo')}: {exc}",
                file=sys.stderr,
            )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    sorted_languages = sorted(
        language_totals.items(),
        key=lambda item: (-item[1], item[0].lower()),
    )

    stats_svg = render_stats_svg(
        username,
        {
            "public_repos": int(user.get("public_repos", 0)),
            "followers": int(user.get("followers", 0)),
            "stars": total_stars,
            "forks": total_forks,
        },
        generated_at,
    )
    languages_svg = render_languages_svg(
        username,
        sorted_languages,
        generated_at,
        len(owned_non_fork_repos),
    )

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "github-stats.svg").write_text(stats_svg, encoding="utf-8")
    (ASSETS_DIR / "top-languages.svg").write_text(languages_svg, encoding="utf-8")

    print(f"Generated SVG cards for {username} in {ASSETS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
