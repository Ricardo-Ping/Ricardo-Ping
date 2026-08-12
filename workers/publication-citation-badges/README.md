# Publication Citation Badges Worker

This Cloudflare Worker serves live citation badges for the profile README.

## Endpoints

- `/badge.svg?doi=<doi>&fallback=<count>&label=OpenAlex`
- `/badge.svg?title=<title>&fallback=<count>&label=OpenAlex`
- `/count.json?doi=<doi>&fallback=<count>`
- `/count.json?title=<title>&fallback=<count>`

The Worker resolves citation counts from OpenAlex at request time and falls back to the cached count included in the URL when OpenAlex is unavailable.

## Deploy

1. Register a `workers.dev` subdomain once in the Cloudflare dashboard if your account has never published a Worker before:

- https://dash.cloudflare.com/?to=/:account/workers/subdomain

2. Authenticate once:

```powershell
$env:PATH='C:\Users\Ricardo_PING\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;' + $env:PATH
& 'C:\Users\Ricardo_PING\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd' dlx wrangler login
```

3. Deploy the Worker:

```powershell
$env:PATH='C:\Users\Ricardo_PING\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;' + $env:PATH
& 'C:\Users\Ricardo_PING\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd' dlx wrangler deploy --config workers/publication-citation-badges/wrangler.jsonc
```

4. Copy the resulting `workers.dev` base URL and set it as the GitHub repository variable `PUBLICATION_CITATION_BADGE_BASE_URL`.

5. Re-run the `Sync Publications` GitHub Action, or run the sync locally with the same environment variable set.

## Optional OpenAlex etiquette

If you want OpenAlex polite-pool identification, set either of these before deploy:

- `OPENALEX_EMAIL`
- `OPENALEX_API_KEY`
