.PHONY: help install test test-unit audit mcp serve clean lint

PYTHON ?= python3
PYTEST ?= pytest

help:
	@echo "cwv-speed-engine Makefile commands:"
	@echo "  make install     - Install package in editable development mode"
	@echo "  make test        - Run all pytest test suites"
	@echo "  make test-unit   - Run MCP and CLI unit test suites"
	@echo "  make audit       - Run performance audit on sample"
	@echo "  make mcp         - Launch stdio MCP server"
	@echo "  make serve       - Launch Speed Studio Material 3 Web UI"
	@echo "  make clean       - Remove cache, build, and temporary artifacts"
	@echo "  make lint        - Check Python code syntax and formatting"

install:
	$(PYTHON) -m pip install -e .

test:
	PYTHONPATH=src $(PYTEST) tests/ -v

test-unit:
	PYTHONPATH=src $(PYTEST) tests/test_mcp.py tests/test_cli.py -v

audit:
	PYTHONPATH=src $(PYTHON) -m cwv_speed_engine.cli audit --help

mcp:
	PYTHONPATH=src $(PYTHON) -m cwv_speed_engine.mcp_server

serve:
	PYTHONPATH=src $(PYTHON) -m cwv_speed_engine.cli serve --port 8095

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache/ __pycache__ src/**/__pycache__ tests/__pycache__

lint:
	$(PYTHON) -m compileall src tests
