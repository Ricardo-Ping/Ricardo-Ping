#!/usr/bin/env python3
"""Generate static SVG cards for the GitHub profile README."""

from __future__ import annotations

import json
import os
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

CARD_BG = "#0d1117"
CARD_BORDER = "#30363d"
TEXT_PRIMARY = "#e6edf3"
TEXT_MUTED = "#8b949e"
TEXT_ACCENT = "#58a6ff"
BOX_BG = "#161b22"
BAR_BG = "#21262d"

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


def format_number(value: int) -> str:
    return f"{value:,}"


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def metric_box(x: int, y: int, title: str, value: str, icon: str) -> str:
    safe_title = escape(title)
    safe_value = escape(value)
    safe_icon = escape(icon)
    return f"""
  <g transform="translate({x},{y})">
    <rect width="350" height="72" rx="14" fill="{BOX_BG}" stroke="{CARD_BORDER}" />
    <text x="20" y="30" font-size="13" fill="{TEXT_MUTED}">{safe_title}</text>
    <text x="20" y="54" font-size="24" font-weight="700" fill="{TEXT_PRIMARY}">{safe_value}</text>
    <text x="320" y="48" text-anchor="middle" font-size="22" fill="{TEXT_ACCENT}">{safe_icon}</text>
  </g>"""


def render_stats_svg(username: str, stats: dict[str, int], generated_at: str) -> str:
    safe_username = escape(username)
    return f"""<svg width="820" height="248" viewBox="0 0 820 248" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="statsTitle statsDesc">
  <title id="statsTitle">{safe_username} GitHub Stats</title>
  <desc id="statsDesc">Auto-generated GitHub profile statistics card.</desc>
  <rect x="1" y="1" width="818" height="246" rx="18" fill="{CARD_BG}" stroke="{CARD_BORDER}" />
  <text x="28" y="42" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="24" font-weight="700" fill="{TEXT_PRIMARY}">GitHub Stats</text>
  <text x="28" y="68" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14" fill="{TEXT_MUTED}">@{safe_username} · public activity snapshot</text>
{metric_box(28, 92, "Public repositories", format_number(stats["public_repos"]), "▣")}
{metric_box(394, 92, "Followers", format_number(stats["followers"]), "◉")}
{metric_box(28, 172, "Total stars", format_number(stats["stars"]), "★")}
{metric_box(394, 172, "Total forks", format_number(stats["forks"]), "⑂")}
  <text x="792" y="228" text-anchor="end" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12" fill="{TEXT_MUTED}">Updated {escape(generated_at)} UTC</text>
</svg>
"""


def render_languages_svg(
    username: str, languages: list[tuple[str, int]], generated_at: str
) -> str:
    safe_username = escape(username)
    total = sum(size for _, size in languages)
    rows: list[str] = []

    if total == 0:
        rows.append(
            f'  <text x="28" y="116" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="16" fill="{TEXT_MUTED}">No language data available yet.</text>'
        )
        height = 160
    else:
        top_languages = languages[:6]
        height = 96 + len(top_languages) * 34 + 28
        for index, (language, size) in enumerate(top_languages):
            percent = size / total * 100
            color = LANGUAGE_COLORS.get(language, TEXT_ACCENT)
            y = 98 + index * 34
            bar_width = max(12, round(560 * percent / 100))
            safe_language = escape(truncate(language, 24))
            rows.append(
                f"""  <g transform="translate(28,{y})">
    <circle cx="6" cy="11" r="6" fill="{color}" />
    <text x="22" y="16" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14" fill="{TEXT_PRIMARY}">{safe_language}</text>
    <text x="734" y="16" text-anchor="end" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" fill="{TEXT_MUTED}">{percent:.1f}%</text>
    <rect x="22" y="22" width="560" height="8" rx="4" fill="{BAR_BG}" />
    <rect x="22" y="22" width="{bar_width}" height="8" rx="4" fill="{color}" />
    <text x="596" y="29" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="11" fill="{TEXT_MUTED}">{format_number(size)} bytes</text>
  </g>"""
            )

    rows_markup = "\n".join(rows)
    return f"""<svg width="820" height="{height}" viewBox="0 0 820 {height}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="langsTitle langsDesc">
  <title id="langsTitle">{safe_username} Top Languages</title>
  <desc id="langsDesc">Auto-generated GitHub profile language distribution card.</desc>
  <rect x="1" y="1" width="818" height="{height - 2}" rx="18" fill="{CARD_BG}" stroke="{CARD_BORDER}" />
  <text x="28" y="42" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="24" font-weight="700" fill="{TEXT_PRIMARY}">Top Languages</text>
  <text x="28" y="68" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="14" fill="{TEXT_MUTED}">@{safe_username} · aggregated from owned public repositories</text>
{rows_markup}
  <text x="792" y="{height - 20}" text-anchor="end" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12" fill="{TEXT_MUTED}">Updated {escape(generated_at)} UTC</text>
</svg>
"""


def main() -> int:
    username = os.environ.get("GITHUB_USERNAME", "Ricardo-Ping").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip() or None

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
        sorted(language_totals.items(), key=lambda item: item[1], reverse=True),
        generated_at,
    )

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "github-stats.svg").write_text(stats_svg, encoding="utf-8")
    (ASSETS_DIR / "top-languages.svg").write_text(languages_svg, encoding="utf-8")

    print(f"Generated SVG cards for {username} in {ASSETS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
