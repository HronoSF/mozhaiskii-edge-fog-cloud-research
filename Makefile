PYTHON ?= python3
PANDOC ?= pandoc
XELATEX ?= xelatex
BUILD := build
SOURCES := figures/topology.svg figures/scenarios.svg figures/task-timeline.svg figures/median-latency.svg
.PHONY: all clean
all:
	$(PYTHON) scripts/generate_median_latency.py
	mkdir -p $(BUILD)/figures
	$(PYTHON) -c "from pathlib import Path; import cairosvg; [(cairosvg.svg2pdf(url=str(p),write_to=str(Path('build')/p.with_suffix('.pdf')))) for p in map(Path, '$(SOURCES)'.split())]"
	sed 's@../figures/@build/figures/@g; s@\.svg)@.pdf)@g' report/scheduling-pilot.md > $(BUILD)/scheduling-pilot.md
	$(PANDOC) -f markdown -t latex --standalone --template=latex/research-report.tex $(BUILD)/scheduling-pilot.md -o $(BUILD)/scheduling-pilot.tex
	$(XELATEX) -interaction=nonstopmode -halt-on-error -output-directory=$(BUILD) $(BUILD)/scheduling-pilot.tex
	$(XELATEX) -interaction=nonstopmode -halt-on-error -output-directory=$(BUILD) $(BUILD)/scheduling-pilot.tex
	cp $(BUILD)/scheduling-pilot.pdf scheduling-pilot.pdf
clean:
	rm -rf $(BUILD) scheduling-pilot.pdf
