# WoW Forever talent planner
#   make            build the WebAssembly engine and the site data
#   make test       engine tests (native), data checks, wasm tests against every class
#   make update     pull the latest game data and rebuild (see README)
#   make serve      preview the site at http://localhost:8000
#   make single     one self-contained HTML file in dist/ (no server needed)

CC      ?= cc
CLANG   ?= clang
PYTHON  ?= python3
WASM    := site/planner.wasm

all: $(WASM) data

$(WASM): core/planner.c core/planner.h
	$(CLANG) --target=wasm32 -O2 -nostdlib -fno-builtin -fvisibility=hidden \
	  -Wall -Wextra -Wl,--no-entry -Wl,--strip-all -o $@ core/planner.c

data:
	$(PYTHON) tools/wfdata.py build

update:
	$(PYTHON) tools/wfdata.py update --stats

test: $(WASM)
	@mkdir -p build
	$(CC) -std=c99 -Wall -Wextra -Icore -o build/test_planner tests/test_planner.c core/planner.c
	./build/test_planner
	$(PYTHON) tools/wfdata.py check
	$(PYTHON) tests/test_update.py
	node tests/test_wasm.mjs

serve: all
	$(PYTHON) -m http.server 8000 --directory site

single: all
	$(PYTHON) tools/bundle.py

clean:
	rm -rf build dist

.PHONY: all data update test serve single clean
