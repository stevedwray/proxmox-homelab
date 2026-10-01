# eval-runner -- lm-evaluation-harness (GPQA, IFEval) as a thin HTTP client
# of Framework's llama-server. Built locally on ai-services-stack by
# deploy-ai-services-stack.yml's "Install eval-runner" play and started one
# run at a time by /usr/local/bin/eval-run -- never a long-lived compose
# service. See docs/eval-runner/plan.md.
FROM python:3.12-slim

# Runs as uid 1000, not root (same convention as deep-research). The
# playbook chowns /srv/eval-runner/results to 1000 to match, and the HF
# cache dir is pre-created here so the named volume mounted over it
# inherits this ownership on first mount.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /home/app/.cache/huggingface \
    && chown -R app:app /home/app/.cache

# Set before the RUN below, not after: nltk 3.10's import guard refuses to
# import anything that resolves under the current working directory, and
# the build's default cwd is / -- which contains the whole stdlib.
WORKDIR /results

# Pinned to the lm_eval release and API/IFEval dependency versions behind
# every GPQA/IFEval number in docs/framework/eval-battery-phase2-plan.md,
# so new results stay comparable with the old ones. No torch/transformers:
# the API model path doesn't need them. Not --only-binary: langdetect,
# rouge-score, sqlitedict and word2number only ship as sdists. openpyxl is
# publish.py's (leaderboard.xlsx), not lm_eval's.
RUN pip install --no-cache-dir \
      "aiohttp==3.14.3" \
      "datasets==5.0.1" \
      "immutabledict==4.3.1" \
      "langdetect==1.0.9" \
      "lm_eval[api,ifeval]==0.4.12" \
      "nltk==3.10.1" \
      "openpyxl==3.1.5" \
      "tenacity==9.1.4"

# Run setup (runmeta.py), scoring summary (summarize.py), Nextcloud
# publishing (publish.py, findings.md -- copied in from docs/eval-runner/ by
# the playbook) and the selftest pieces. Copied after the pip layer so editing them doesn't invalidate the
# slow install. The test_*.py unit tests stay in the repo, not the image.
COPY findings.md mock_nextcloud.py mock_openai.py publish.py runmeta.py selftest.sh selftest_checks.py summarize.py /opt/eval-runner/
RUN chmod 0755 /opt/eval-runner/selftest.sh

USER app
ENV HOME=/home/app
RUN python -c "import nltk; nltk.download('punkt_tab', quiet=True)"

ENTRYPOINT ["lm_eval"]
