#!/usr/bin/env python3
import json
import os
import re
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional

README_PATH = Path("README.md")
SEED_PATH = Path("data/publications_seed.json")
CACHE_PATH = Path("data/publications_cache.json")
START_MARKER = "<!-- PUBS:START -->"
END_MARKER = "<!-- PUBS:END -->"


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_text(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def doi_to_url(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    return f"https://doi.org/{doi}"


def normalize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    authors = [a.strip() for a in entry.get("authors", []) if str(a).strip()]
    return {
        "year": int(entry.get("year", 0) or 0),
        "title": str(entry.get("title", "")).strip(),
        "authors": authors,
        "venue": str(entry.get("venue", "")).strip(),
        "doi": (entry.get("doi") or "").strip() or None,
        "paper_url": (entry.get("paper_url") or "").strip() or None,
        "citations": entry.get("citations", None),
    }


def load_seed() -> List[Dict[str, Any]]:
    if not SEED_PATH.exists():
        return []
    # Accept UTF-8 with or without BOM to keep CI resilient to editor encoding differences.
    data = json.loads(SEED_PATH.read_text(encoding="utf-8-sig"))
    return [normalize_entry(x) for x in data]


def extract_orcid_external_ids(work: Dict[str, Any]) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    groups = work.get("external-ids", {}).get("external-id", []) or []
    for item in groups:
        id_type = (item.get("external-id-type") or "").lower()
        id_value = item.get("external-id-value") or ""
        if id_type and id_value:
            ids[id_type] = id_value
    return ids


def fetch_orcid_publications(orcid_id: str) -> List[Dict[str, Any]]:
    headers = {"Accept": "application/json"}
    root = f"https://pub.orcid.org/v3.0/{orcid_id}"
    works = fetch_json(f"{root}/works", headers=headers)
    groups = works.get("group", []) or []
    out: List[Dict[str, Any]] = []

    for g in groups:
        summaries = g.get("work-summary", []) or []
        if not summaries:
            continue
        put_code = summaries[0].get("put-code")
        if not put_code:
            continue
        detail = fetch_json(f"{root}/work/{put_code}", headers=headers)

        title = detail.get("title", {}).get("title", {}).get("value", "").strip()
        if not title:
            continue

        journal = detail.get("journal-title", {}).get("value", "").strip()
        year_str = detail.get("publication-date", {}).get("year", {}).get("value")
        year = int(year_str) if year_str and str(year_str).isdigit() else 0

        contributors = detail.get("contributors", {}).get("contributor", []) or []
        authors: List[str] = []
        for c in contributors:
            name = c.get("credit-name", {}).get("value", "").strip()
            if name:
                authors.append(name)

        ids = extract_orcid_external_ids(detail)
        doi = ids.get("doi")
        url = detail.get("url", {}).get("value")

        out.append(
            normalize_entry(
                {
                    "year": year,
                    "title": title,
                    "authors": authors,
                    "venue": journal,
                    "doi": doi,
                    "paper_url": url,
                }
            )
        )

    return out


def fetch_scholar_publications(user_id: str) -> List[Dict[str, Any]]:
    url = (
        "https://scholar.google.com/citations?"
        + urllib.parse.urlencode(
            {
                "user": user_id,
                "hl": "en",
                "view_op": "list_works",
                "sortby": "pubdate",
                "pagesize": "100",
            }
        )
    )
    html = fetch_text(url, headers={"User-Agent": "Mozilla/5.0"})
    rows = re.findall(r'<tr class="gsc_a_tr".*?</tr>', html, flags=re.S)

    out: List[Dict[str, Any]] = []
    for row in rows:
        title_m = re.search(r'class="gsc_a_at"[^>]*>(.*?)</a>', row, flags=re.S)
        if not title_m:
            continue
        title = unescape(re.sub(r"<.*?>", "", title_m.group(1))).strip()

        gray = re.findall(r'<div class="gs_gray">(.*?)</div>', row, flags=re.S)
        authors = []
        venue = ""
        if gray:
            authors = [x.strip() for x in unescape(re.sub(r"<.*?>", "", gray[0])).split(",") if x.strip()]
        if len(gray) > 1:
            venue = unescape(re.sub(r"<.*?>", "", gray[1])).strip()

        year_m = re.search(r'<span class="gsc_a_h gsc_a_hc gs_ibl">(\d{4})</span>', row)
        year = int(year_m.group(1)) if year_m else 0

        cited_m = re.search(r'class="gsc_a_ac gs_ibl">(\d+)</a>', row)
        citations = int(cited_m.group(1)) if cited_m else None

        out.append(
            normalize_entry(
                {
                    "year": year,
                    "title": title,
                    "authors": authors,
                    "venue": venue,
                    "citations": citations,
                }
            )
        )

    return out


def enrich_with_crossref(entries: List[Dict[str, Any]]) -> None:
    for e in entries:
        if e.get("doi") and e.get("authors") and e.get("venue"):
            continue
        query = urllib.parse.quote(e["title"])
        url = f"https://api.crossref.org/works?query.bibliographic={query}&rows=1"
        try:
            result = fetch_json(url)
            item = (result.get("message", {}).get("items") or [{}])[0]
        except Exception:
            continue

        if not e.get("doi") and item.get("DOI"):
            e["doi"] = item["DOI"]

        if not e.get("venue"):
            container = item.get("container-title") or []
            if container:
                e["venue"] = container[0]

        if not e.get("authors"):
            authors = []
            for a in item.get("author", []) or []:
                given = a.get("given", "").strip()
                family = a.get("family", "").strip()
                name = f"{given} {family}".strip()
                if name:
                    authors.append(name)
            if authors:
                e["authors"] = authors


def is_first_author(entry: Dict[str, Any], primary_last_name: str) -> bool:
    if not entry.get("authors"):
        return False
    first = entry["authors"][0].lower()
    return primary_last_name.lower() in first


def citation_badge(citations: Any) -> str:
    if citations is None:
        return '<img src="https://img.shields.io/badge/Citations-N%2FA-6e7681?style=flat-square" alt="citations n/a"/>'
    return f'<img src="https://img.shields.io/badge/Citations-{citations}-1f6feb?style=flat-square" alt="citations {citations}"/>'


def render_table(entries: List[Dict[str, Any]]) -> str:
    if not entries:
        return "<p>No publications found.</p>"

    lines = ["<table>"]
    for e in entries:
        link = doi_to_url(e.get("doi")) or e.get("paper_url")
        safe_title = e["title"].replace("|", "\\|")
        title_html = f'<a href="{link}"><strong>{safe_title}</strong></a>' if link else f"<strong>{safe_title}</strong>"
        authors = ", ".join(e.get("authors") or ["N/A"])
        venue = e.get("venue") or "N/A"
        links: List[str] = []
        if e.get("doi"):
            links.append(f'<a href="{doi_to_url(e["doi"])}">DOI</a>')
        if e.get("paper_url"):
            links.append(f'<a href="{e["paper_url"]}">Paper</a>')
        links_html = " | ".join(links) if links else "-"

        lines.append("  <tr>")
        lines.append(f"    <td><strong>{e.get('year', 0) or 'N/A'}</strong></td>")
        lines.append(f"    <td>{title_html}<br/>Authors: {authors}<br/>{venue}</td>")
        lines.append(f"    <td>{links_html}<br/>{citation_badge(e.get('citations'))}</td>")
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def render_publication_section(entries: List[Dict[str, Any]], source_label: str, primary_last_name: str) -> str:
    ordered = sorted(entries, key=lambda x: (x.get("year", 0), x.get("title", "")), reverse=True)
    first = [e for e in ordered if is_first_author(e, primary_last_name)]
    co = [e for e in ordered if not is_first_author(e, primary_last_name)]

    parts = [
        START_MARKER,
        f"> Auto-synced source: **{source_label}**",
        "",
        "## Publications (First Author)",
        "",
        render_table(first),
        "",
        "## Publications (Co-Author)",
        "",
        render_table(co),
        END_MARKER,
    ]
    return "\n".join(parts)


def replace_between_markers(text: str, replacement: str) -> str:
    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.S)
    if pattern.search(text):
        return pattern.sub(replacement, text)

    anchor = "## GitHub Stats"
    idx = text.find(anchor)
    if idx == -1:
        return text + "\n\n" + replacement + "\n"
    return text[:idx] + replacement + "\n\n" + text[idx:]


def main() -> int:
    source = os.getenv("PUBLICATION_SOURCE", "orcid").strip().lower()
    orcid_id = os.getenv("ORCID_ID", "").strip()
    scholar_id = os.getenv("GOOGLE_SCHOLAR_ID", "").strip()
    primary_last_name = os.getenv("PRIMARY_AUTHOR_LAST_NAME", "ping").strip()

    entries: List[Dict[str, Any]] = []
    source_label = "seed"

    try:
        if source == "scholar" and scholar_id:
            entries = fetch_scholar_publications(scholar_id)
            source_label = f"Google Scholar ({scholar_id})"
        elif source == "orcid" and orcid_id:
            entries = fetch_orcid_publications(orcid_id)
            source_label = f"ORCID ({orcid_id})"
        elif orcid_id:
            entries = fetch_orcid_publications(orcid_id)
            source_label = f"ORCID ({orcid_id})"
        elif scholar_id:
            entries = fetch_scholar_publications(scholar_id)
            source_label = f"Google Scholar ({scholar_id})"
    except Exception as exc:
        print(f"[warn] remote source fetch failed: {exc}")

    if not entries:
        entries = load_seed()
        source_label = "seed data"

    enrich_with_crossref(entries)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = README_PATH.read_text(encoding="utf-8")
    block = render_publication_section(entries, source_label, primary_last_name)
    updated = replace_between_markers(readme, block)
    README_PATH.write_text(updated, encoding="utf-8")

    print(f"Updated README publications from {source_label}. total={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
