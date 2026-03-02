# ─── Photogen Telegram Bot Makefile ────────────────────────────────────────────
# Usage: make <target>

DC = sudo docker compose

# ─── Rebuild ──────────────────────────────────────────────────────────────────

.PHONY: rebuild

rebuild:
	$(DC) up -d --build

# ─── Logs ─────────────────────────────────────────────────────────────────────

.PHONY: logs

logs:
	$(DC) logs --tail=50 -f

# ─── Status ───────────────────────────────────────────────────────────────────

.PHONY: status

status:
	@$(DC) ps
