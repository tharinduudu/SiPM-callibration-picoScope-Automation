PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: test smoke compile check

test:
	$(PYTHON) -m unittest discover -s app/tests -v

smoke:
	$(PYTHON) app/tests/smoke_test.py --tools automation

compile:
	$(PYTHON) -m compileall -q app automation pi

check: compile test smoke
