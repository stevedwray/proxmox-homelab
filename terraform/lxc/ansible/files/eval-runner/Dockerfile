# eval-runner -- lm-evaluation-harness (GPQA, IFEval) as a thin HTTP client
# of Framework's llama-server. Built locally on ai-services-stack by
# deploy-ai-services-stack.yml's "Install eval-runner" play and started one
# run at a time by /usr/local/bin/eval-run -- never a long-lived compose
# service. See docs/eval-runner/plan.md.
FROM python:3.12-slim

# Pinned to the lm_eval release and API/IFEval dependency versions behind
# every GPQA/IFEval number in docs/framework/eval-battery-phase2-plan.md,
# so new results stay comparable with the old ones. No torch/transformers:
# the API model path doesn't need them.
RUN pip install --no-cache-dir \
      "lm_eval[api,ifeval]==0.4.12" \
      "datasets==5.0.1" \
      "aiohttp==3.14.3" \
      "tenacity==9.1.4" \
      "langdetect==1.0.9" \
      "immutabledict==4.3.1" \
      "nltk==3.10.1" \
    && python -c "import nltk; nltk.download('punkt_tab', quiet=True)"

WORKDIR /results
ENTRYPOINT ["lm_eval"]
