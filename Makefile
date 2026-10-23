PYTHON ?= python3
XELATEX ?= xelatex
CAIRO_LIBDIR ?= /opt/homebrew/lib
.PHONY: all figures verify
all: figures
	DYLD_FALLBACK_LIBRARY_PATH="$(CAIRO_LIBDIR)" "$(PYTHON)" scripts/build_report.py
	"$(XELATEX)" -no-shell-escape -interaction=nonstopmode -halt-on-error -output-directory=build report/scheduling-report.tex
	"$(XELATEX)" -no-shell-escape -interaction=nonstopmode -halt-on-error -output-directory=build report/scheduling-report.tex
	cp build/scheduling-report.pdf report/UPV-EHU_Scheduling_Report_A01-A03.pdf
figures:
	"$(PYTHON)" scripts/generate_figures.py
verify:
	"$(PYTHON)" scripts/verify_release.py
