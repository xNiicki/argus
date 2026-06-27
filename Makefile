.PHONY: help up down restart logs pull build validate test narrator-test promtool amtool fmt

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "\033[36m%-16s\033[0m %s\n",$$1,$$2}'

up: ## Start the stack (pulls images from GHCR)
	docker compose up -d

down: ## Stop the stack
	docker compose down

restart: ## Pull latest images and recreate
	docker compose pull && docker compose up -d --force-recreate

pull: ## Pull the latest images from GHCR
	docker compose pull

IMG := ghcr.io/xniicki/argus
TAG ?= latest
build: ## Build all images locally (tagged so `make up` uses them)
	docker build -t $(IMG)-narrator:$(TAG)     ./narrator
	docker build -t $(IMG)-prometheus:$(TAG)   ./prometheus
	docker build -t $(IMG)-alertmanager:$(TAG) ./alertmanager
	docker build -t $(IMG)-blackbox:$(TAG)     ./blackbox
	docker build -t $(IMG)-loki:$(TAG)         ./loki

logs: ## Tail narrator logs
	docker compose logs -f narrator

validate: promtool amtool ## Validate configs + compose
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
