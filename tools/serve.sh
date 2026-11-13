#!/usr/bin/env bash
# Start the web app (http://localhost:8000) with run 2's model settings (12 Nov 2026), copied from
# run 2's run script, so "All three reports" matches run 2's quality and cost (~USD 0.50).
# The OpenRouter key is read from secrets/openrouter.txt by investsync/config.py; it is never printed.
# Usage: tools/serve.sh            (PORT=8001 tools/serve.sh for another port)
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
export LLM_MODEL=openrouter/deepseek/deepseek-v4.1-flash-1017
export OPENROUTER_PROVIDER=${OPENROUTER_PROVIDER:-'{"order":["deepinfra/fp8","cohere/fp8","novita/fp8"],"allow_fallbacks":false}'}
export LLM_JUDGE_MODEL=${LLM_JUDGE_MODEL-openrouter/anthropic/claude-sonnet-5.5} LLM_JUDGE_EFFORT=medium
export LLM_LEARNER_MODEL=${LLM_LEARNER_MODEL-openrouter/anthropic/claude-sonnet-5.5}
export OPENROUTER_JUDGE_PROVIDER=${OPENROUTER_JUDGE_PROVIDER:-'{"order":["anthropic","google-vertex/global","amazon-bedrock"],"allow_fallbacks":false}'}
export LLM_DEEP_MODEL= LLM_WRITER_MODEL= LLM_CHECK_MODEL=          # all Flash (the primary model)
export LLM_DEEP_EFFORT=high LLM_WRITER_EFFORT=high LLM_CHECK_EFFORT=high LLM_WRITER_THINKING=enabled
export RESEARCH=1 CLAIM_CHECK=1 FORECAST=1 BRIEF=1 PEER_PE_BASIS=forward RATING_BASIS=analyst OVERALL_VIEW=0
export RESEARCH_CHUNKS=${RESEARCH_CHUNKS:-70}        # run 1 read 60; +10 for the call summary and post-results events
export FORECAST_TIER=${FORECAST_TIER-}               # decided 11 Nov: the house forecast stays on Flash (FORECAST_TIER=judge would move it to Sonnet)
export LLM_NUM_RETRIES=${LLM_NUM_RETRIES:-8}
exec uvicorn api.main:app --host 127.0.0.1 --port "${PORT:-8000}"
