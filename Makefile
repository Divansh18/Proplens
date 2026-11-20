.PHONY: install run test lint scrape

install:
	python3.11 -m pip install -r requirements.txt

run:
	python3.11 -m uvicorn app.main:app --reload

test:
	python3.11 -m pytest -q

lint:
	python3.11 -m ruff check .
	python3.11 -m ruff format --check .

scrape:
	python3.11 -m scraper.run --source all
