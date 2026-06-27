.PHONY: help up dev down restart logs reload pull portable validate test narrator-test promtool amtool fmt

DEV := -f docker-compose.yml -f docker-compose.build.yml

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "\033[36m%-16s\033[0m %s\n",$$1,$$2}'

up: ## Start the central stack (pulls narrator image from GHCR)
	docker compose up -d

dev: ## Start the stack building narrator from local source
	docker compose $(DEV) up -d --build

pull: ## Pull the latest narrator image from GHCR
	docker compose pull narrator

down: ## Stop the central stack
	docker compose down

restart: ## Recreate all services (pulls latest images)
	docker compose pull && docker compose up -d --force-recreate

logs: ## Tail narrator logs
	docker compose logs -f narrator

reload: ## Hot-reload Prometheus config (no restart)
	curl -fsS -XPOST http://localhost:9090/-/reload && echo "prometheus reloaded"

portable: ## Regenerate the self-contained docker-compose.portable.yml from source configs
	@python3 -c 'import yaml' 2>/dev/null && PY=python3 || PY=narrator/.venv/bin/python; \
		$$PY scripts/gen-portable-compose.py

validate: promtool amtool ## Validate all config (prometheus rules + alertmanager + compose)
	docker compose config -q && echo "compose OK"

promtool: ## Check Prometheus config + alert rules
	docker run --rm --entrypoint promtool -v $(PWD)/prometheus:/etc/prometheus \
		prom/prometheus:v2.55.1 check config /etc/prometheus/prometheus.yml

amtool: ## Check Alertmanager config
	docker run --rm --entrypoint amtool -v $(PWD)/alertmanager:/etc/alertmanager \
		prom/alertmanager:v0.27.0 check-config /etc/alertmanager/alertmanager.yml

test: narrator-test ## Run all tests

narrator-test: ## Run narrator unit tests (bootstraps a local venv)
	cd narrator && test -d .venv || python3 -m venv .venv
	cd narrator && .venv/bin/pip install -q pyyaml pytest httpx
	cd narrator && .venv/bin/python -m pytest -q

fmt: ## Format narrator code (if ruff installed)
	cd narrator && ruff format . || true
