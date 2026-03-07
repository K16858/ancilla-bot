#!/usr/bin/env bash
# Run batch summarize (load .env, then python -m ancilla_bot.cli.main batch summarize).
# For use from cron etc. Use absolute path in crontab, e.g.:
#   0 3 * * * /path/to/ancilla-bot/scripts/run_batch_summarize.sh

set -e
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  . ./.env
  set +a
fi

if [ -d .venv ] && [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python
fi

exec "$PYTHON" -m ancilla_bot.cli.main batch summarize
