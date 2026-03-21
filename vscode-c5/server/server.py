#!/usr/bin/env python3
"""
C5 Language Server
Provides LSP features: hover, diagnostics, and more.
"""

import sys
import os
import json
import re
from pathlib import Path

# Pattern to strip ANSI escape sequences
ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Try to import pygls
try:
    from pygls.lsp.server import LanguageServer, types
    PYGLS_AVAILABLE = True
except ImportError:
    PYGLS_AVAILABLE = False
    print("Warning: pygls not installed. Install with: pip install pygls", file=sys.stderr)

# Add the C5 compiler directory to Python path
# Default location: ~/projects/c5
# If your compiler is elsewhere, modify this path.
project_root = Path.home() / "projects" / "c5"
if not project_root.exists():
    # Fallback: try relative to extension (for development)
    project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from c5c.lexer import lex
    from c5c.parser import Parser
    from c5c.analyzer import SemanticAnalyzer
    from c5c.compiler import _collect_macros, _expand_macros
    C5_AVAILABLE = True
except ImportError as e:
    C5_AVAILABLE = False
    print(f"Warning: Could not import C5 compiler modules: {e}", file=sys.stderr)


class C5LanguageServer(LanguageServer):
    """C5 Language Server implementation."""

    def __init__(self):
        super().__init__('c5-language-server', '0.1')
        self.documents = {}  # uri -> content
        self.analysis_cache = {}  # uri -> (ast, analyzer, diagnostics)

        # Register handlers
        @self.feature('initialize')
        def initialize(ls, params):
            return {
                'capabilities': {
                    'textDocumentSync': {
                        'openClose': True,
                        'change': 1  # TextDocumentSyncKind.Full
                    },
                    'hoverProvider': True,
                    'diagnosticProvider': {
                        'interFileDependencies': False,
                        'workspaceDiagnostics': False
                    }
                }
            }

        @self.feature('textDocument/didOpen')
        def did_open(ls, params):
            uri = params.text_document.uri
            text = params.text_document.text
            self.documents[uri] = text
            self._analyze_document(uri, text)

        @self.feature('textDocument/didChange')
        def did_change(ls, params):
            uri = params.text_document.uri
            # Full sync - replace entire content
            # content_changes is always present in LSP
            for change in params.content_changes:
                if change.range is None:  # Full text update
                    self.documents[uri] = change.text
                    break
            self._analyze_document(uri, self.documents.get(uri, ""))

        @self.feature('textDocument/didSave')
        def did_save(ls, params):
            uri = params.text_document.uri
            if uri in self.documents:
                self._analyze_document(uri, self.documents[uri])

        @self.feature('textDocument/hover')
        def hover(ls, params):
            uri = params.text_document.uri
            position = params.position

            if uri not in self.analysis_cache:
                return None

            analyzer = self.analysis_cache[uri]['analyzer']
            text = self.documents.get(uri, "")

            # Find the symbol at the given position
            symbol_info = self._find_symbol_at_position(analyzer, text, position)

            if symbol_info:
                return types.Hover(contents=symbol_info)

            return None

        @self.feature('workspace/didChangeWatchedFiles')
        def did_change_watched_files(ls, params):
            """Handle file system changes for watched files (e.g., includes)."""
            for change in params.changes:
                uri = change.uri
                # If a changed file is in our analysis cache, re-analyze dependent files
                # For simplicity, we clear the cache and re-analyze open documents
                if uri in self.analysis_cache:
                    # Invalidate this file and any files that include it
                    # For now, just re-analyze the main file when it changes
                    if uri in self.documents:
                        self._analyze_document(uri, self.documents[uri])
            return None

    def _resolve_include_path(self, fname, base_dir):
        """Resolve an include filename to an absolute path."""
        search_paths = [
            base_dir,
            os.path.join(base_dir, '..', 'c5include'),
            os.path.join(os.getcwd(), 'c5include'),
            os.path.join(str(project_root), 'c5include')
        ]
        for p in search_paths:
            fullpath = os.path.normpath(os.path.join(p, fname))
            if os.path.isfile(fullpath):
                return os.path.abspath(fullpath)
        return None

    def _collect_include_uris_from_ast(self, ast, base_dir, include_uris, visited):
        """Recursively collect include URIs from the AST."""
        for node in ast:
            if isinstance(node, tuple) and node[0] == 'include':
                fname = node[1]
                inc_path = self._resolve_include_path(fname, base_dir)
                if inc_path:
                    inc_uri = Path(inc_path).as_uri()
                    if inc_uri not in visited:
                        visited.add(inc_uri)
                        include_uris.append(inc_uri)

    def _merge_analyzer_symbols(self, dest, src, namespace=None):
        """Merge symbols from src analyzer into dest analyzer, optionally applying a namespace prefix."""
        prefix = f"{namespace}::" if namespace else ""
        # Merge functions
        for name, info in src.functions.items():
            new_name = prefix + name
            if new_name not in dest.functions:
                dest.functions[new_name] = info
        # Merge structs
        for name, fields in src.structs.items():
            new_name = prefix + name
            if new_name not in dest.structs:
                dest.structs[new_name] = fields
        # Merge enums
        for name, values in src.enums.items():
            new_name = prefix + name
            if new_name not in dest.enums:
                dest.enums[new_name] = values
        # Merge types
        for name, types in src.types.items():
            new_name = prefix + name
            if new_name not in dest.types:
                dest.types[new_name] = types
        # Merge typeops
        for type_name, ops in src.typeops.items():
            new_type_name = prefix + type_name
            if new_type_name not in dest.typeops:
                dest.typeops[new_type_name] = {}
            for op, info in ops.items():
                if op not in dest.typeops[new_type_name]:
                    dest.typeops[new_type_name][op] = info
        # Merge global variables (scope 0)
        for var_name, var_type in src.scopes[0].items():
            new_var_name = prefix + var_name
            if new_var_name not in dest.scopes[0]:
                dest.scopes[0][new_var_name] = var_type
        # Merge library symbols: add all merged symbol names to library sets
        # This ensures symbols from includes are treated as library (no dead code warnings)
        dest.library_funcs.update([prefix + name for name in src.functions.keys()])
        dest.library_vars.update([prefix + name for name in src.scopes[0].keys()])

    def _collect_macros_from_ast(self, ast, macros_dict):
        """Collect all macro definitions from an AST and add them to macros_dict."""
        for node in ast:
            if isinstance(node, tuple) and node[0] == 'macro':
                _, name, params, body, _ = node
                macros_dict[name] = (params, body)

    def _analyze_document(self, uri, text, _visited=None):
        """Analyze a C5 document and produce diagnostics."""
        if not C5_AVAILABLE:
            return

        if _visited is None:
            _visited = set()

        filepath = uri_to_path(uri)
        base_dir = os.path.dirname(filepath)

        diagnostics = []
        try:
            # Parse AST
            tokens = lex(text)
            parser = Parser(tokens)
            ast = parser.parse_program()

            # Create analyzer early for error reporting
            analyzer = SemanticAnalyzer(source_code=text, filename=filepath)

            # Collect include URIs (direct)
            include_uris = []
            self._collect_include_uris_from_ast(ast, base_dir, include_uris, _visited)

            # Analyze included files recursively
            for inc_uri in include_uris:
                if inc_uri in self.analysis_cache:
                    continue
                inc_path = uri_to_path(inc_uri)
                try:
                    with open(inc_path, 'r') as f:
                        inc_text = f.read()
                    # Recursively analyze this include with the same visited set
                    self._analyze_document(inc_uri, inc_text, _visited)
                except Exception as e:
                    analyzer.add_error("E999", f"Failed to read include: {e}", loc=None)

            # After includes are analyzed, merge their symbols into the main analyzer
            for inc_uri in include_uris:
                if inc_uri in self.analysis_cache:
                    inc_analyzer = self.analysis_cache[inc_uri]['analyzer']
                    # Determine namespace from the included file's name (e.g., std from std.c5h)
                    inc_path = uri_to_path(inc_uri)
                    inc_namespace = os.path.splitext(os.path.basename(inc_path))[0]
                    self._merge_analyzer_symbols(analyzer, inc_analyzer, namespace=inc_namespace)

            # Collect and expand macros (like the compiler does)
            # First, collect macros from the main AST and all included ASTs
            macros = {}
            # Add macros from main file
            self._collect_macros_from_ast(ast, macros)
            # Add macros from included files (they are already in the cache)
            for inc_uri in include_uris:
                if inc_uri in self.analysis_cache:
                    inc_ast = self.analysis_cache[inc_uri]['ast']
                    inc_path = uri_to_path(inc_uri)
                    inc_namespace = os.path.splitext(os.path.basename(inc_path))[0]
                    # Collect macros with namespacing
                    inc_macros = {}
                    self._collect_macros_from_ast(inc_ast, inc_macros)
                    # Namespace the macro names
                    for macro_name in list(inc_macros.keys()):
                        namespaced_name = f"{inc_namespace}::{macro_name}"
                        macros[namespaced_name] = inc_macros[macro_name]

            # Expand macros in the main AST
            expanded_ast = _expand_macros(ast, macros)

            # Strip include, detect_once, and macro definitions from AST before analysis
            cleaned_ast = [node for node in expanded_ast if not (isinstance(node, tuple) and node[0] in ('include', 'libinclude', 'detect_once', 'macro'))]

            # Analyze the cleaned AST with merged symbols
            analyzer.analyze(cleaned_ast, require_main=False, exit_on_error=False)

            # Cache analysis results for hover
            self.analysis_cache[uri] = {
                'ast': ast,
                'analyzer': analyzer,
                'diagnostics': diagnostics
            }

        except Exception as e:
            pass

        # Publish diagnostics
        self.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))

    def _strip_ansi(self, s):
        """Remove ANSI escape sequences from a string."""
        return ANSI_ESCAPE_RE.sub('', s)

    def _parse_diagnostic(self, diag_str, is_error=True):
        """Parse an error or warning string into an LSP diagnostic."""
        # Strip ANSI codes
        clean = self._strip_ansi(diag_str)
        # Take only the first line to avoid multi-line issues
        first_line = clean.split('\n')[0]
        # Pattern: filename:line:col: (error|warning): message
        # Use regex to handle possible colons in filename
        pattern = r'^(.+):(\d+):(\d+):\s*(?:error|warning)\s*:\s*(.*)$'
        match = re.match(pattern, first_line)
        if match:
            filename, line_str, col_str, message = match.groups()
            try:
                line = int(line_str) - 1
                col = int(col_str)
                severity = types.DiagnosticSeverity.Error if is_error else types.DiagnosticSeverity.Warning
                code = "C5_ERROR" if is_error else "C5_WARNING"
                return types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line, character=col),
                        end=types.Position(line=line, character=col + 10)
                    ),
                    severity=severity,
                    code=code,
                    message=message,
                    source="C5 Language Server"
                )
            except ValueError:
                pass
        # Fallback: create diagnostic at line 0 with full cleaned message
        severity = types.DiagnosticSeverity.Error if is_error else types.DiagnosticSeverity.Warning
        code = "C5_ERROR" if is_error else "C5_WARNING"
        return types.Diagnostic(
            range=types.Range(
                start=types.Position(line=0, character=0),
                end=types.Position(line=0, character=10)
            ),
            severity=severity,
            code=code,
            message=clean,
            source="C5 Language Server"
        )

    def _parse_error_to_diagnostic(self, error_str):
        """Parse an error string from the analyzer into an LSP diagnostic."""
        return self._parse_diagnostic(error_str, True)

    def _parse_warning_to_diagnostic(self, warning_str):
        """Parse a warning string from the analyzer into an LSP diagnostic."""
        return self._parse_diagnostic(warning_str, False)

    def _find_symbol_at_position(self, analyzer, text, position):
        """Find symbol information at the given position."""
        lines = text.split('\n')
        if position.line >= len(lines):
            return None

        line = lines[position.line]
        col = position.character

        # Extract the qualified name at the cursor
        word = self._extract_qualified_name(line, col)
        if not word:
            return None

        # Check if we're looking at a typeop operator pattern
        typeop_match = self._extract_typeop_at_position(line, col)
        if typeop_match:
            type_name, op = typeop_match
            if type_name in analyzer.typeops and op in analyzer.typeops[type_name]:
                ret_ty, params, body, loc = analyzer.typeops[type_name][op]
                param_str = ', '.join([f"{p[0]} {p[1]}" for p in params])
                return f"**typeop** `{type_name}::{op}`\n\nReturn type: `{ret_ty}`\n\nParameters: `{param_str}`"

        # Check if the word is a type that has typeops (show type info)
        if word in analyzer.typeops:
            ops_list = ', '.join(analyzer.typeops[word].keys())
            if word in analyzer.structs:
                fields = analyzer.structs[word]
                field_list = '\n'.join([f"- {f[0]} {f[1]}" for f in fields])
                return f"**struct** `{word}`\n\nFields:\n{field_list}\n\nType operators: {ops_list}"
            elif word in analyzer.types:
                types = analyzer.types[word]
                type_list = ', '.join(types)
                return f"**type** `{word}`\n\nAllowed types: `{type_list}`\n\nType operators: {ops_list}"
            else:
                return f"**type** `{word}`\n\nType operators: `{ops_list}`"

        # Check functions
        if word in analyzer.functions:
            ret_ty, param_count, is_varargs, is_extern = analyzer.functions[word]
            param_str = f"{param_count} argument{'s' if param_count != 1 else ''}"
            if is_varargs:
                param_str += ", ..."
            return f"**function** `{word}`\n\nReturn type: `{ret_ty}`\n\nParameters: {param_str}\n\n{'extern' if is_extern else ''}"

        # Check structs
        if word in analyzer.structs:
            fields = analyzer.structs[word]
            field_list = '\n'.join([f"- {f[0]} {f[1]}" for f in fields])
            return f"**struct** `{word}`\n\nFields:\n{field_list}"

        # Check enums
        if word in analyzer.enums:
            values = analyzer.enums[word]
            # values can be either a dict (name->value) or a list of names
            if isinstance(values, dict):
                value_list = '\n'.join([f"- {k} = {v}" for k, v in values.items()])
            else:
                value_list = '\n'.join([f"- {v}" for v in values])
            return f"**enum** `{word}`\n\nValues:\n{value_list}"

        # Check type definitions (union/variant)
        if word in analyzer.types:
            types = analyzer.types[word]
            type_list = ', '.join(types)
            return f"**type** `{word}`\n\nAllowed types: `{type_list}`"

        # Check variables in current scope (global and any remaining)
        for scope in analyzer.scopes:
            for name, var_type in scope.items():
                if word == name:
                    return f"**variable** `{name}`\n\nType: `{var_type}`"

        # Check other variables (e.g., local variables that have been popped from scopes)
        if hasattr(analyzer, 'var_types') and word in analyzer.var_types:
            return f"**variable** `{word}`\n\nType: `{analyzer.var_types[word]}`"

        return None

    def _extract_qualified_name(self, line: str, col: int) -> str:
        """Extract the qualified identifier (with ::) at the given column."""
        if col >= len(line):
            return ""
        if not (line[col].isalnum() or line[col] == '_'):
            return ""
        # Find end of simple identifier (alphanumeric + underscore)
        end = col
        while end < len(line) and (line[end].isalnum() or line[end] == '_'):
            end += 1
        # Find start of simple identifier
        start = col
        while start > 0 and (line[start-1].isalnum() or line[start-1] == '_'):
            start -= 1
        full_name = line[start:end]
        # Prepend any namespace qualifiers
        pos = start
        while pos > 0:
            if pos >= 2 and line[pos-2:pos] == '::':
                ns_end = pos - 2
                ns_start = ns_end
                while ns_start > 0 and (line[ns_start-1].isalnum() or line[ns_start-1] == '_'):
                    ns_start -= 1
                if ns_start < ns_end:
                    namespace = line[ns_start:ns_end]
                    if namespace:
                        full_name = namespace + '::' + full_name
                        pos = ns_start
                        continue
            break
        return full_name

    def _extract_typeop_at_position(self, line: str, col: int) -> tuple:
        """Check if position is on a typeop operator pattern."""
        import re
        # Pattern: typeop TypeName.operator or typeop TypeName == etc.
        # We want to extract TypeName and the operator
        # Look behind for "typeop" and TypeName
        # This is tricky - we'll look at the line and try to match

        # Simplified: look for pattern like "typeop BetterString.join" or "typeop BetterString =="
        pattern = r'typeop\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:([a-zA-Z_][a-zA-Z0-9_]*)|([=!<>]=|&&|\|\||<<|>>|->|\.\.\.|[+\-*/%&|^~=<>!]))'
        for match in re.finditer(pattern, line):
            if match.start(1) <= col <= match.end(2) or match.start(2) <= col <= match.end(2):
                type_name = match.group(1)
                op = match.group(2) if match.group(2) else match.group(3)
                return (type_name, op)
        return None

    def _symbol_contains_position(self, name: str, loc: tuple, word: str, pos: tuple) -> bool:
        """Check if a symbol at location matches the word and position."""
        line, col = loc
        # loc is 1-based, pos[0] is 0-based
        return word == name and pos[0] == (line - 1)

    def start(self):
        """Start the language server."""
        self.start_io()

    def stop(self):
        """Stop the language server."""
        super().stop()


def uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a filesystem path."""
    if uri.startswith('file://'):
        path = uri[7:]
        # Decode URL encoding
        import urllib.parse
        path = urllib.parse.unquote(path)
        return path
    return uri


def main():
    """Main entry point."""
    if not PYGLS_AVAILABLE:
        print("Error: pygls is not installed. Install with: pip install pygls", file=sys.stderr)
        sys.exit(1)

    if not C5_AVAILABLE:
        print("Error: C5 compiler modules not found.", file=sys.stderr)
        sys.exit(1)

    server = C5LanguageServer()
    server.start()


if __name__ == '__main__':
    main()
