# C5 Support for VS Code

This extension provides support for the C5 programming language in Visual Studio Code.

## Features

- **Syntax Highlighting**: Full syntax highlighting for C5 files (`.c5`, `.c5h`).
- **Error Handling**: Real-time syntax and semantic error flagging using the C5 compiler's diagnostic engine.
- **Language Configuration**: Support for comments, brackets, and auto-closing pairs.

## Requirements

- Python 3 must be installed and available on your PATH as `python3`.
- The C5 compiler source must be located at `~/projects/c5`.

## Installation

1. Copy this folder to your VS Code extensions directory:
   - Linux/macOS: `~/.vscode/extensions/`
   - Windows: `%USERPROFILE%\.vscode\extensions\`
2. Restart VS Code.

## Troubleshooting

If the LSP server isn't starting or you're not seeing errors/semantic highlighting:

1. **Check Output Channel**: Open View → Output, select "C5 Language Server" from the dropdown to see server logs.

2. **Verify Python 3**: Run `python3 --version` in terminal. Python 3 must be available.

3. **Check C5 Compiler Location**: The extension expects the C5 compiler at `~/projects/c5`. 
   If your compiler is elsewhere, edit `server/server.py` line 6 to point to the correct path.

4. **Test Server Manually**: 
   ```bash
   python3 server/server.py
   ```
   The server should start without import errors. If you see import errors, the C5 compiler modules are missing.

5. **Enable Extension Logging**: 
   - Open Command Palette (Ctrl+Shift+P)
   - Run "Developer: Set Log Level"
   - Choose "Debug" and check the Extension logs for activation errors.

6. **Restart VS Code**: After installation, fully restart VS Code (not just the window).

7. **Activation Events**: The extension activates when:
   - Opening a `.c5` or `.c5h` file, OR
   - A `build.c5b` file is found in the workspace.

## License

MIT
