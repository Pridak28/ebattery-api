# Backend ops scripts

## health_check.py
Polls /api/v1/data/health-detailed and prints alerts.

Usage:
  ./venv/bin/python -m scripts.health_check
  ./venv/bin/python -m scripts.health_check --url http://prod-host/api/v1/data/health-detailed
  ./venv/bin/python -m scripts.health_check --quiet --threshold-stale 14
  ./venv/bin/python -m scripts.health_check --json | jq

Exit codes:
  0  no alerts (healthy)
  1  one or more ALERT lines emitted
  2  backend unreachable / invalid JSON

Cron example (every 6 hours):
  0 */6 * * * cd /path/to/backend && ./venv/bin/python -m scripts.health_check --quiet || mail -s "BESS alert" you@example.com
