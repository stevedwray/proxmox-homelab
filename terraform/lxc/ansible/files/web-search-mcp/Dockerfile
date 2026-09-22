# web-search-mcp -- headless-browser web search MCP server, fronted by
# mcpo (github.com/open-webui/mcpo) so OpenWebUI's OpenAPI-based Tool
# Server client can call it. OpenWebUI's own native MCP client only speaks
# streamable-HTTP (see open_webui/utils/mcp/client.py); web-search-mcp is
# stdio-only (built for LM Studio/LibreChat, which spawn it directly), so
# mcpo bridges stdio -> OpenAPI HTTP in front of it.
#
# Replaces Brave's metered Search API (Free-tier 2000 req/month quota,
# exhausted 2026-09-16) and SearXNG's degraded scraped-engine results
# (Google API access restrictions upstream) with a real headless-browser
# search against Bing/Brave/DuckDuckGo -- no API key, no quota.
#
# Built locally on this LXC from source copied in by the ansible
# controller (same pattern as this repo's docs-rag-mcp/cve-mcp-server) --
# single consumer (OpenWebUI on this same stack), so no dedicated Harbor
# project is warranted (revisit if that changes).
#
# Microsoft's official playwright image ships Node + all Playwright browser OS deps
# preinstalled -- avoids a second `npx playwright install --with-deps`
# apt layer on this 2-core LXC. Must match the exact playwright version
# web-search-mcp's package-lock.json actually resolves at the pinned tag
# below (checked directly: v0.3.2 locks playwright 1.54.2, not the
# ^1.48.0 range package.json alone would suggest) -- a mismatched base
# image's bundled browser binaries don't satisfy a different npm
# `playwright` version, which triggers a fresh browser download on
# `npm ci` that this apt-only image has no way to serve.
FROM mcr.microsoft.com/playwright:v1.54.2-noble

# mcpo (the stdio-MCP -> OpenAPI HTTP bridge) is a Python package; the
# Playwright base image is Debian/Node-only, so add Python + pip here.
# mcp==1.30.0 pinned explicitly alongside mcpo: mcpo 0.0.20 only declares
# `mcp>=1.17.0` (unbounded), which resolves to whatever's newest on
# PyPI -- confirmed live this pulled mcp 2.2.0 and broke immediately
# (`ImportError: cannot import name 'streamablehttp_client' from
# 'mcp.client.streamable_http'`, a real breaking API change upstream that
# mcpo 0.0.20's own code hasn't caught up to). 1.30.0 is the latest
# stable 1.x release and confirmed working.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --break-system-packages mcpo==0.0.20 mcp==1.30.0

WORKDIR /opt/web-search-mcp

# Pinned to v0.3.2 (github.com/mrkrsl/web-search-mcp), not a moving
# branch -- matches this repo's pin-by-digest convention for third-party
# images/sources elsewhere in this stack.
# pwuser (uid 1001) ships in the playwright base image specifically for
# running headless Chromium as non-root; reused here rather than adding
# a separate app user. Final chown covers the cloned/built app dir.
RUN git clone --branch v0.3.2 --depth 1 \
        https://github.com/mrkrsl/web-search-mcp.git . \
    && npm ci \
    && npm run build \
    && npm prune --omit=dev \
    && chown -R pwuser:pwuser /opt/web-search-mcp
USER pwuser

# BROWSER_TYPES restricts the general-purpose browser pool used for
# Bing search and content extraction to a single Chromium instance --
# this LXC has a 6GB memory ceiling shared with
# OpenWebUI/SearXNG/ollama-reliability-proxy (see stack.yaml's memory
# bump comment), and extra concurrent Chromium instances aren't needed
# for one interactive assistant's search volume.
#
# NOT a full chromium-only guarantee, though: web-search-mcp's Brave
# search path launches Firefox directly, unconditionally, regardless of
# this setting (confirmed live 2026-09-15 debugging a workstation
# install that had only installed Chromium -- Brave failed there with
# "Executable doesn't exist at .../firefox", while this image's base
# (mcr.microsoft.com/playwright) ships Firefox/WebKit binaries
# unconditionally too, so it works here whether or not this env var
# says so). Real memory use under a Brave-engine search is therefore
# Chromium's pool plus one on-demand Firefox instance, not Chromium
# alone -- factor that in before lowering the memory ceiling above.
# ENABLE_RELEVANCE_CHECKING=false (flipped from true 2026-09-22, see
# fix/deep-research-web-search-mcp): the upstream quality heuristic
# (search-engine.ts assessResultQuality()) is a naive keyword-overlap
# scorer -- it strips common/short words from the query, then scores a
# result by literal keyword matches in its title/description/URL only.
# Confirmed live: query "Ed Sheeran real name" reduces to keywords
# [sheeran, real, name] ("Ed" is filtered, length <= 2), and Bing's
# actual, correct top result ("Edward Christopher Sheeran... is an
# English singer...") scored 0.00/1.0 and was discarded as "low quality"
# purely because it doesn't contain the literal words "real"/"name" --
# a false-negative in the heuristic, not a real quality problem with
# Bing's result. With checking disabled, Bing's first real results are
# accepted immediately (quality treated as 1.0, the "excellent, return
# now" path) instead of falling through to Brave (whose scraper CSS
# selectors -- .result/.fdb -- matched 0 elements against Brave's
# current page layout, a separate upstream page-drift issue this repo
# doesn't control) and then DuckDuckGo's axios fallback (hit a bot-
# challenge page, HTTP 202, 0 parsed results). Two independent test
# queries returned 0 results end-to-end with checking enabled; this is
# the actual fix, not a tuning tweak -- lowering RELEVANCE_THRESHOLD
# alone would not have helped a genuine 0.00 score.
ENV BROWSER_TYPES=chromium \
    MAX_BROWSERS=1 \
    BROWSER_HEADLESS=true \
    ENABLE_RELEVANCE_CHECKING=false

EXPOSE 8000

# --api-key is passed via $MCPO_API_KEY (set at container run time from
# this compose file's own env, sourced from SOPS) rather than baked in
# here, so the key never lands in image layers/history.
#
# Confirmed live (local build+run, 2026-09-15): web-search-mcp writes a
# few human-readable startup banner lines to stdout ("Web Search MCP
# Server started", etc) before its real JSON-RPC traffic begins, which
# mcpo's stdio client can't parse and logs as JSONRPCMessage validation
# errors on container start. Benign -- mcpo skips the unparsable lines
# and moves on; a direct end-to-end call to /get-web-search-summaries
# through the running bridge returned real results. Don't mistake these
# startup-only log lines for a broken deploy.
CMD ["sh", "-c", "mcpo --host 0.0.0.0 --port 8000 --api-key \"$MCPO_API_KEY\" -- node dist/index.js"]
