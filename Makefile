# ─── Photogen Telegram Bot Makefile ────────────────────────────────────────────
# Usage: make <target>

DC = sudo docker compose
DC_PROD2 = sudo docker compose -f docker-compose-prod2.yml

# ─── Rebuild ──────────────────────────────────────────────────────────────────

.PHONY: rebuild

rebuild:
	$(DC) up -d --build

.PHONY: prod2-up prod2-logs prod2-status

prod2-up:
	$(DC_PROD2) up -d --build

prod2-logs:
	$(DC_PROD2) logs --tail=50 -f

prod2-status:
	@$(DC_PROD2) ps

# ─── Logs ─────────────────────────────────────────────────────────────────────

.PHONY: logs

logs:
	$(DC) logs --tail=50 -f

# ─── Status ───────────────────────────────────────────────────────────────────

.PHONY: status

status:
	@$(DC) ps
