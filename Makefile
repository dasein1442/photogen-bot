# ─── Photogen Telegram Bot Makefile ────────────────────────────────────────────
# Usage: make <target>

DC = sudo docker compose
DC_STAGE = sudo docker compose -f docker-compose-stage.yml
DC_PROD2 = sudo docker compose -f docker-compose-prod2.yml

# ─── Rebuild ──────────────────────────────────────────────────────────────────

.PHONY: rebuild

rebuild:
	$(DC) up -d --build

.PHONY: stage-up stage-logs stage-status

stage-up:
	$(DC_STAGE) up -d --build

stage-logs:
	$(DC_STAGE) logs --tail=50 -f

stage-status:
	@$(DC_STAGE) ps

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
