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
# ENABLE_RELEVANCE_CHECKING=true (reverted 2026-09-22 after a same-day
# flip to false -- see fix/deep-research-web-search-mcp git history for
# the full story, kept rather than squashed away because the failure it
# documents is real and worth not repeating).
#
# Disabling this check does remove a real false-negative (Bing's
# genuinely correct result for "Ed Sheeran real name" scored 0.00/1.0
# under the upstream naive keyword-overlap heuristic and was discarded
# -- see assessResultQuality() in search-engine.ts). But confirmed live
# immediately after deploying that fix: with checking disabled, Bing's
# scraper in this pinned version (v0.3.2) returns confidently-wrong,
# unrelated results for ordinary queries -- "Ed Sheeran real name"
# returned erectile-dysfunction articles, "python asyncio timeout best
# practices" returned YouTube Music links. This isn't a quality-scoring
# edge case; the scraper itself appears to be reading the wrong DOM
# elements on Bing's current page layout (likely drifted since this
# version was pinned, same class of issue as Brave's stale .result/.fdb
# selectors below). Accepting these results unfiltered is worse than
# the original 0-results failure it was meant to fix -- a research
# agent has no signal that the results are garbage and could cite them.
# Left ON until either a newer upstream tag fixes Bing's scraper, or a
# real fix is found -- see docs/deep-research/current-state.md.
ENV BROWSER_TYPES=chromium \
    MAX_BROWSERS=1 \
    BROWSER_HEADLESS=true \
    ENABLE_RELEVANCE_CHECKING=true

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
