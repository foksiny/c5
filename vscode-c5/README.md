# C5 Support for VS Code

This extension provides support for the C5 programming language in Visual Studio Code.

## Features

- **Syntax Highlighting**: Full syntax highlighting for C5 files (`.c5`, `.c5h`), including support for `type` and `typeop` constructs.
- **Error Handling**: Real-time syntax and semantic error flagging using the C5 compiler's diagnostic engine.
- **Hover Information**: Hover over functions, types, structs, enums, variables, and type operators to see their signatures and type information.
- **Language Configuration**: Support for comments, brackets, and auto-closing pairs.

## Requirements

- Python 3 must be installed and available on your PATH as `python3`.
- The C5 compiler source must be located at `~/projects/c5`.
- Python package `pygls` must be installed for the language server.

## Installation

### 1. Install VS Code Extension

1. Copy this folder to your VS Code extensions directory:
   - Linux/macOS: `~/.vscode/extensions/`
   - Windows: `%USERPROFILE%\.vscode\extensions\`
2. Restart VS Code.

### 2. Install Python Dependencies

The language server requires the `pygls` package. Install it with:

```bash
cd vscode-c5/server
pip3 install -r requirements.txt
```

Or install directly:

```bash
pip3 install pygls
```

## Troubleshooting

If the LSP server isn't starting or you're not seeing errors/semantic highlighting:

1. **Check Output Channel**: Open View → Output, select "C5 Language Server" from the dropdown to see server logs.

2. **Verify Python 3**: Run `python3 --version` in terminal. Python 3 must be available.

3. **Verify pygls**: Run `python3 -c "import pygls"` to ensure pygls is installed.

4. **Check C5 Compiler Location**: The extension expects the C5 compiler at `~/projects/c5`.
   If your compiler is elsewhere, edit `server/server.py` line 5 to point to the correct path.

5. **Test Server Manually**:
   ```bash
   cd vscode-c5/server
   python3 server/server.py
   ```
   The server should start without import errors. If you see import errors, the C5 compiler modules are missing.

6. **Enable Extension Logging**:
   - Open Command Palette (Ctrl+Shift+P)
   - Run "Developer: Set Log Level"
   - Choose "Debug" and check the Extension logs for activation errors.

7. **Restart VS Code**: After installation, fully restart VS Code (not just the window).

8. **Activation Events**: The extension activates when:
   - Opening a `.c5` or `.c5h` file, OR
   - A `build.c5b` file is found in the workspace.

## Language Features

### Hover Support
Hover over any symbol to see:
- Functions: return type and parameters
- Type operators (`typeop`): return type and parameters
- Structs: field list
- Enums: value list
- Type definitions: allowed types
- Variables: type information

### Diagnostics
The language server provides real-time error and warning diagnostics for:
- Syntax errors
- Type mismatches
- Undefined symbols
- Unused variables/functions
- And more from the C5 compiler's analysis engine.

## Known Limitations

- The language server currently analyzes files individually. Cross-file dependencies are not fully resolved (library files are recognized but not fully analyzed together).
- Hover information for symbols from included files may be limited.

## License

MIT
