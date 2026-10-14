# Shortcuts for macOS / Linux (on Windows use the commands in README.md).
PY ?= python3

.PHONY: setup backend frontend test doctor demo smoke check docker

setup:                ## install backend + frontend dependencies and the Firefox browser
	cd backend && $(PY) -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt && python -m playwright install --with-deps firefox
	cd frontend && npm install
	@test -f backend/.env || cp backend/.env.example backend/.env
	@test -f frontend/.env.local || cp frontend/.env.example frontend/.env.local
	@echo "Done. Run 'make backend' in one terminal and 'make frontend' in another."

backend:              ## API on http://localhost:8000
	cd backend && . .venv/bin/activate && python -m app

frontend:             ## website on http://localhost:3000
	cd frontend && npm run dev

doctor:               ## check ffmpeg, browser and settings
	cd backend && . .venv/bin/activate && python -m app.cli doctor

demo:                 ## make one ad from the command line: make demo URL=https://example.com
	cd backend && . .venv/bin/activate && python -m app.cli demo $(URL) --out ../ad-demo.mp4

test:                 ## backend tests
	cd backend && . .venv/bin/activate && python -m pytest

check:                ## frontend/backend contract + types
	$(PY) scripts/check_contract.py
	cd frontend && npm run typecheck

smoke:                ## end-to-end test against the running backend
	$(PY) scripts/smoke_test.py

docker:               ## whole app in containers
	docker compose up --build
