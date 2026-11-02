# Orchanium: common tasks. Run `make` to list them.
.DEFAULT_GOAL := help

help:  ## list the tasks
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

env:  ## create .env from the template (then add your META_API_KEY)
	@test -f .env || cp .env.example .env
	@echo "Edit .env and set META_API_KEY"

up: env  ## build and start everything with Docker (UI on http://localhost:5173)
	docker compose up --build

down:  ## stop the containers
	docker compose down

dev-api:  ## run the backend locally with reload (port 8000)
	cd backend && uvicorn orchanium.api:app --port 8000 --reload

dev-ui:  ## run the frontend locally (port 5173)
	cd frontend && npm install && npm run dev

test:  ## lint and run every test
	ruff check backend scripts --config backend/ruff.toml
	cd backend && python -m pytest -q
	cd frontend && npx tsc --noEmit

index:  ## optional: download and build the 1.45M-reaction patent index (~20 min)
	python scripts/download_uspto.py
	python scripts/build_uspto_index.py
	python scripts/build_class_priors.py
