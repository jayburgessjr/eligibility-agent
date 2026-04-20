.PHONY: install demo demo-default demo-ineligible demo-incomplete server test lint help

help:
	@echo ""
	@echo "eligibility-agent"
	@echo "-----------------"
	@echo "make install          Install dependencies"
	@echo "make demo             Run with eligible applicant (local fixture)"
	@echo "make demo-ineligible  Run with prior-default applicant"
	@echo "make demo-incomplete  Run with missing SAP field (→ human_review)"
	@echo "make server           Start the MCP regulation server on :8000"
	@echo "make test             Run test suite (no API key required)"
	@echo "make lint             Run pyflakes"
	@echo ""

install:
	pip install -r requirements.txt

demo:
	python -m agent.run \
		--query "Is this applicant eligible for Title IV federal aid?" \
		--applicant examples/applicant_eligible.json \
		--verbose

demo-ineligible:
	python -m agent.run \
		--query "Is this applicant eligible for Title IV federal aid?" \
		--applicant examples/applicant_default.json \
		--verbose

demo-incomplete:
	python -m agent.run \
		--query "Is this applicant eligible for Title IV federal aid?" \
		--applicant examples/applicant_incomplete.json \
		--verbose

server:
	python mcp_server/server.py

test:
	python -m pytest tests/ -v

lint:
	python -m pyflakes agent/ tests/ mcp_server/
