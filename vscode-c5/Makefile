EXT_DIR = $(HOME)/.vscode/extensions/c5-support

all: install

install:
	@echo "Installing dependencies..."
	npm install
	@echo "Copying to extensions folder: $(EXT_DIR)"
	mkdir -p $(EXT_DIR)
	cp -r * $(EXT_DIR)
	@echo "Done! Please restart VS Code."

clean:
	rm -rf node_modules package-lock.json

.PHONY: all install clean
