.PHONY:	setup patch pypi patch minor major build publish test
export PYTHONPATH := $(shell pwd)/tests:$(shell pwd):$(PYTHONPATH)
export PROJECT_NAME := $$(basename $$(pwd))

setup:
		uv sync
patch:
		uv run bump-my-version bump --allow-dirty patch
minor:
		uv run bump-my-version bump --allow-dirty minor
major:
		uv run bump-my-version bump --allow-dirty major
pypi:
		uv build
		uv publish
build:
		uv build
publish:
		rm -rf dist/
		hatch build
		hatch publish
test:
		uv run pytest
