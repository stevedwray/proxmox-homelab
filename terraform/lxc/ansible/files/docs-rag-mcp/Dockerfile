# docs-rag-mcp -- see docs/coding-stack/plan.md for the design this
# implements. Built locally on the host from source copied by the
# ansible controller (same pattern as this LXC's existing cve-mcp-server
# service) -- no other consumer of this image yet, so no dedicated Harbor
# project is warranted (revisit if that changes).
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app
WORKDIR /home/app

COPY pyproject.toml README.md ./
COPY docs_rag_mcp ./docs_rag_mcp
COPY schema.sql ./schema.sql

RUN pip install --no-cache-dir .

USER app

EXPOSE 8001

CMD ["python", "-m", "docs_rag_mcp.main"]
