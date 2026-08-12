const DEFAULT_LABEL = "OpenAlex";
const DEFAULT_LABEL_COLOR = "#30363d";
const DEFAULT_VALUE_COLOR = "#1f6feb";
const FALLBACK_VALUE_COLOR = "#6e7681";
const FONT_FAMILY = "Verdana,Geneva,DejaVu Sans,sans-serif";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "") {
      return new Response(
        [
          "Ricardo-Ping publication citation badge worker",
          "",
          "Use /badge.svg?doi=<doi>&fallback=<count>&label=OpenAlex",
          "Or /badge.svg?title=<title>&fallback=<count>&label=OpenAlex",
          "Use /count.json?doi=<doi>&fallback=<count> for raw JSON",
        ].join("\n"),
        {
          headers: {
            "content-type": "text/plain; charset=utf-8",
            "cache-control": "public, max-age=300",
          },
        },
      );
    }

    if (url.pathname === "/badge.svg") {
      return respondFromCache(request, ctx, async () => renderBadgeResponse(url, env));
    }

    if (url.pathname === "/count.json") {
      return respondFromCache(request, ctx, async () => renderJsonResponse(url, env));
    }

    return new Response("Not found", {
      status: 404,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  },
};

async function respondFromCache(request, ctx, buildResponse) {
  const cache = typeof caches !== "undefined" ? caches.default : null;

  if (cache) {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
  }

  const response = await buildResponse();

  if (cache && ctx?.waitUntil) {
    ctx.waitUntil(cache.put(request, response.clone()));
  }

  return response;
}

async function renderJsonResponse(url, env) {
  const citationRecord = await resolveCitationRecord(url, env);
  return jsonResponse(citationRecord);
}

async function renderBadgeResponse(url, env) {
  const citationRecord = await resolveCitationRecord(url, env);
  const label = trimLabel(url.searchParams.get("label") || env.BADGE_LABEL || DEFAULT_LABEL);
  const badgeSvg = renderBadgeSvg(label, citationRecord);

  return new Response(badgeSvg, {
    headers: svgHeaders(),
  });
}

async function resolveCitationRecord(url, env) {
  const fallback = parseOptionalInteger(url.searchParams.get("fallback"));
  const doi = normalizeDoi(url.searchParams.get("doi"));
  const title = (url.searchParams.get("title") || "").trim();

  if (!doi && !title) {
    return {
      citations: fallback,
      source: fallback === null ? "unavailable" : "fallback",
      doi: null,
      title,
      updatedAt: new Date().toISOString(),
      error: "Either doi or title is required.",
    };
  }

  try {
    const liveRecord = await fetchOpenAlexCitation({ doi, title, env });
    if (liveRecord && typeof liveRecord.citations === "number") {
      return {
        ...liveRecord,
        source: "openalex",
        updatedAt: new Date().toISOString(),
      };
    }
  } catch (error) {
    return {
      citations: fallback,
      source: fallback === null ? "unavailable" : "fallback",
      doi,
      title,
      updatedAt: new Date().toISOString(),
      error: error instanceof Error ? error.message : String(error),
    };
  }

  return {
    citations: fallback,
    source: fallback === null ? "unavailable" : "fallback",
    doi,
    title,
    updatedAt: new Date().toISOString(),
  };
}

async function fetchOpenAlexCitation({ doi, title, env }) {
  const requestUrl = buildOpenAlexUrl({ doi, title, env });
  const response = await fetch(requestUrl, {
    headers: {
      "user-agent": "Ricardo-Ping-publication-citation-badges/1.0",
      accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`OpenAlex request failed with status ${response.status}`);
  }

  const payload = await response.json();
  if (doi) {
    return {
      citations: optionalInteger(payload.cited_by_count),
      doi,
      title: payload.display_name || title,
      openalexId: payload.id || null,
    };
  }

  const candidates = payload.results || [];
  const bestMatch = selectBestTitleMatch(title, candidates);
  if (!bestMatch) {
    return null;
  }

  return {
    citations: optionalInteger(bestMatch.cited_by_count),
    doi: normalizeDoi(bestMatch.doi),
    title: bestMatch.display_name || title,
    openalexId: bestMatch.id || null,
  };
}

function buildOpenAlexUrl({ doi, title, env }) {
  if (doi) {
    const workId = encodeURIComponent(`https://doi.org/${doi}`);
    const url = new URL(`https://api.openalex.org/works/${workId}`);
    attachOpenAlexAuth(url, env);
    return url.toString();
  }

  const url = new URL("https://api.openalex.org/works");
  url.searchParams.set("search", title);
  url.searchParams.set("per-page", "5");
  attachOpenAlexAuth(url, env);
  return url.toString();
}

function attachOpenAlexAuth(url, env) {
  if (env.OPENALEX_EMAIL) {
    url.searchParams.set("mailto", env.OPENALEX_EMAIL);
  }
  if (env.OPENALEX_API_KEY) {
    url.searchParams.set("api_key", env.OPENALEX_API_KEY);
  }
}

function selectBestTitleMatch(targetTitle, candidates) {
  let bestCandidate = null;
  let bestScore = 0;

  for (const candidate of candidates) {
    const score = scoreTitleMatch(targetTitle, candidate?.display_name || "");
    if (score > bestScore) {
      bestScore = score;
      bestCandidate = candidate;
    }
  }

  return bestScore >= 0.88 ? bestCandidate : null;
}

function scoreTitleMatch(left, right) {
  const leftKey = normalizeTitleKey(left);
  const rightKey = normalizeTitleKey(right);
  if (!leftKey || !rightKey) {
    return 0;
  }
  if (leftKey === rightKey) {
    return 1;
  }

  const leftTokens = new Set(leftKey.split(" "));
  const rightTokens = new Set(rightKey.split(" "));
  const overlap = [...leftTokens].filter((token) => rightTokens.has(token)).length;
  const unionSize = new Set([...leftTokens, ...rightTokens]).size || 1;
  const tokenScore = overlap / unionSize;

  const substringBonus =
    leftKey.includes(rightKey) || rightKey.includes(leftKey) ? 0.12 : 0;

  return Math.min(1, tokenScore + substringBonus);
}

function normalizeTitleKey(title) {
  return String(title || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function normalizeDoi(doi) {
  if (!doi) {
    return null;
  }
  return String(doi)
    .trim()
    .replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")
    .replace(/^doi:/i, "");
}

function optionalInteger(value) {
  return Number.isInteger(value) ? value : parseOptionalInteger(value);
}

function parseOptionalInteger(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number.parseInt(String(value), 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function trimLabel(label) {
  const safeLabel = String(label || DEFAULT_LABEL).trim();
  if (!safeLabel) {
    return DEFAULT_LABEL;
  }
  return safeLabel.length > 24 ? `${safeLabel.slice(0, 21)}...` : safeLabel;
}

function renderBadgeSvg(label, citationRecord) {
  const valueText =
    citationRecord.citations === null || citationRecord.citations === undefined
      ? "N/A"
      : String(citationRecord.citations);
  const valueColor =
    citationRecord.source === "openalex" ? DEFAULT_VALUE_COLOR : FALLBACK_VALUE_COLOR;
  const titleText = escapeXml(
    `${label}: ${valueText} (${citationRecord.source})`,
  );

  const labelWidth = Math.max(52, Math.round(estimateTextWidth(label) + 18));
  const valueWidth = Math.max(26, Math.round(estimateTextWidth(valueText) + 18));
  const totalWidth = labelWidth + valueWidth;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${totalWidth}" height="20" role="img" aria-label="${titleText}">
  <title>${titleText}</title>
  <linearGradient id="badge-fill" x2="0" y2="100%">
    <stop offset="0" stop-color="#fff" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="badge-clip">
    <rect width="${totalWidth}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#badge-clip)">
    <rect width="${labelWidth}" height="20" fill="${DEFAULT_LABEL_COLOR}"/>
    <rect x="${labelWidth}" width="${valueWidth}" height="20" fill="${valueColor}"/>
    <rect width="${totalWidth}" height="20" fill="url(#badge-fill)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="11">
    <text x="${Math.round(labelWidth / 2)}" y="15" fill="#010101" fill-opacity=".3">${escapeXml(label)}</text>
    <text x="${Math.round(labelWidth / 2)}" y="14">${escapeXml(label)}</text>
    <text x="${labelWidth + Math.round(valueWidth / 2)}" y="15" fill="#010101" fill-opacity=".3">${escapeXml(valueText)}</text>
    <text x="${labelWidth + Math.round(valueWidth / 2)}" y="14">${escapeXml(valueText)}</text>
  </g>
</svg>`;
}

function estimateTextWidth(text) {
  return String(text || "").length * 6.8;
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function svgHeaders() {
  return {
    "content-type": "image/svg+xml; charset=utf-8",
    "cache-control": "public, max-age=21600, s-maxage=21600, stale-while-revalidate=86400",
    "access-control-allow-origin": "*",
  };
}

function jsonResponse(payload) {
  return new Response(JSON.stringify(payload, null, 2), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=21600, s-maxage=21600, stale-while-revalidate=86400",
      "access-control-allow-origin": "*",
    },
  });
}
