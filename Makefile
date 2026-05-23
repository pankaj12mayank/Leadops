.PHONY: setup dev dev-backend dev-frontend build clean test lint

setup:
	python -m venv venv
	pip install -r requirements.txt
	playwright install chromium
	cd frontend && npm install

dev:
	npm run dev

dev-backend:
	python -m uvicorn api.server:app --reload --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

clean:
	rm -rf frontend/dist temp screenshots
	find exports -type f \( -name '*.csv' -o -name '*.json' -o -name '*.parquet' -o -name '*.xlsx' \) -delete

test:
	pytest
	cd frontend && npx vitest run

lint:
	ruff check .
	cd frontend && npx tsc --noEmit
