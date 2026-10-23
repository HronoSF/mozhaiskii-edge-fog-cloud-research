PYTHON ?= python3
XELATEX ?= xelatex
CAIRO_LIBDIR ?= /opt/homebrew/lib
.PHONY: all figures verify test report-verify
all: figures
	DYLD_FALLBACK_LIBRARY_PATH="$(CAIRO_LIBDIR)" "$(PYTHON)" scripts/build_report.py
	"$(XELATEX)" -no-shell-escape -interaction=nonstopmode -halt-on-error -output-directory=build report/scheduling-report.tex
	"$(XELATEX)" -no-shell-escape -interaction=nonstopmode -halt-on-error -output-directory=build report/scheduling-report.tex
	@echo "Rebuilt PDF: build/scheduling-report.pdf (canonical PDF unchanged)"
figures:
	"$(PYTHON)" scripts/generate_figures.py
verify:
	"$(PYTHON)" scripts/verify_release.py
test:
	"$(PYTHON)" -m unittest discover -s tests -v
	PYTHONPATH=experiment/tests/scheduling "$(PYTHON)" -m unittest discover -s experiment/tests/scheduling/madt_scheduling/tests -p 'test_*.py' -v
report-verify:
	"$(PYTHON)" scripts/verify_report.py build/scheduling-report.pdf
