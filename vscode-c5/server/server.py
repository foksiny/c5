#!/usr/bin/env python3
"""
C5 Language Server
Provides LSP features: hover support.
"""

import sys
import os
import re
from pathlib import Path

try:
    from pygls.lsp.server import LanguageServer
    PYGLS_AVAILABLE = True
except ImportError as e:
    print(f"Error importing pygls: {e}", file=sys.stderr)
    PYGLS_AVAILABLE = False

project_root = Path.home() / "projects" / "c5"
if not project_root.exists():
    project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

C5_AVAILABLE = False
try:
    from c5c.lexer import lex
    from c5c.parser import Parser
    from c5c.analyzer import SemanticAnalyzer
    C5_AVAILABLE = True
except ImportError:
    pass


class C5LanguageServer(LanguageServer):
    """C5 Language Server implementation."""

    def __init__(self):
        super().__init__('c5-language-server', '0.1')
        self.documents = {}
        self.analysis_cache = {}

        @self.feature('initialize')
        def initialize(ls, params):
            return {
                'capabilities': {
                    'textDocumentSync': {
                        'openClose': True,
                        'change': 1
                    },
                    'hoverProvider': True
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
            for change in params.content_changes:
                if change.range is None:
                    self.documents[uri] = change.text
                    break
            self._analyze_document(uri, self.documents.get(uri, ""))

        @self.feature('textDocument/didSave')
        def did_save(ls, params):
            pass

        @self.feature('textDocument/hover')
        def hover(ls, params):
            uri = params.text_document.uri
            position = params.position

            if uri not in self.analysis_cache:
                return None

            analyzer = self.analysis_cache[uri].get('analyzer')
            if not analyzer:
                return None

            text = self.documents.get(uri, "")
            symbol_info = self._find_symbol_at_position(analyzer, text, position)

            if symbol_info:
                return {'contents': symbol_info}

            return None

        @self.feature('workspace/didChangeWatchedFiles')
        def did_change_watched_files(ls, params):
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
        """Merge symbols from src analyzer into dest analyzer."""
        prefix = f"{namespace}::" if namespace else ""
        for name, info in src.functions.items():
            new_name = prefix + name
            if new_name not in dest.functions:
                dest.functions[new_name] = info
        for name, fields in src.structs.items():
            new_name = prefix + name
            if new_name not in dest.structs:
                dest.structs[new_name] = fields
        for name, values in src.enums.items():
            new_name = prefix + name
            if new_name not in dest.enums:
                dest.enums[new_name] = values
        for name, types in src.types.items():
            new_name = prefix + name
            if new_name not in dest.types:
                dest.types[new_name] = types
        for type_name, ops in src.typeops.items():
            new_type_name = prefix + type_name
            if new_type_name not in dest.typeops:
                dest.typeops[new_type_name] = {}
            for op, info in ops.items():
                if op not in dest.typeops[new_type_name]:
                    dest.typeops[new_type_name][op] = info
        for var_name, var_type in src.scopes[0].items():
            new_var_name = prefix + var_name
            if new_var_name not in dest.scopes[0]:
                dest.scopes[0][new_var_name] = var_type
        dest.library_funcs.update([prefix + name for name in src.functions.keys()])
        dest.library_vars.update([prefix + name for name in src.scopes[0].keys()])

    def _analyze_document(self, uri, text, _visited=None):
        """Analyze a C5 document for hover support."""
        if not C5_AVAILABLE:
            return

        if _visited is None:
            _visited = set()

        filepath = uri_to_path(uri)
        base_dir = os.path.dirname(filepath)

        try:
            tokens = lex(text)
            parser = Parser(tokens)
            ast = parser.parse_program()

            analyzer = SemanticAnalyzer(source_code=text, filename=filepath)

            include_uris = []
            self._collect_include_uris_from_ast(ast, base_dir, include_uris, _visited)

            for inc_uri in include_uris:
                if inc_uri in self.analysis_cache:
                    continue
                inc_path = uri_to_path(inc_uri)
                try:
                    with open(inc_path, 'r') as f:
                        inc_text = f.read()
                    self._analyze_document(inc_uri, inc_text, _visited)
                except Exception:
                    pass

            for inc_uri in include_uris:
                if inc_uri in self.analysis_cache:
                    inc_analyzer = self.analysis_cache[inc_uri].get('analyzer')
                    if inc_analyzer:
                        inc_path = uri_to_path(inc_uri)
                        inc_namespace = os.path.splitext(os.path.basename(inc_path))[0]
                        self._merge_analyzer_symbols(analyzer, inc_analyzer, namespace=inc_namespace)

            cleaned_ast = [node for node in ast if not (isinstance(node, tuple) and node[0] in ('include', 'libinclude', 'detect_once'))]
            analyzer.analyze(cleaned_ast, require_main=False, exit_on_error=False)

            self.analysis_cache[uri] = {
                'ast': ast,
                'analyzer': analyzer
            }

        except Exception:
            pass

    def _find_symbol_at_position(self, analyzer, text, position):
        """Find symbol information at the given position."""
        lines = text.split('\n')
        if position.line >= len(lines):
            return None

        line = lines[position.line]
        col = position.character

        word = self._extract_qualified_name(line, col)
        if not word:
            return None

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
                return f"**type** `{word}`\n\nType operators: {ops_list}"

        if word in analyzer.functions:
            ret_ty, param_count, is_varargs, is_extern = analyzer.functions[word]
            param_str = f"{param_count} argument{'s' if param_count != 1 else ''}"
            if is_varargs:
                param_str += ", ..."
            return f"**function** `{word}`\n\nReturn type: `{ret_ty}`\n\nParameters: {param_str}"

        if word in analyzer.structs:
            fields = analyzer.structs[word]
            field_list = '\n'.join([f"- {f[0]} {f[1]}" for f in fields])
            return f"**struct** `{word}`\n\nFields:\n{field_list}"

        if word in analyzer.enums:
            values = analyzer.enums[word]
            if isinstance(values, dict):
                value_list = '\n'.join([f"- {k} = {v}" for k, v in values.items()])
            else:
                value_list = '\n'.join([f"- {v}" for v in values])
            return f"**enum** `{word}`\n\nValues:\n{value_list}"

        if word in analyzer.types:
            types = analyzer.types[word]
            type_list = ', '.join(types)
            return f"**type** `{word}`\n\nAllowed types: `{type_list}`"

        for scope in analyzer.scopes:
            for name, var_type in scope.items():
                if word == name:
                    return f"**variable** `{name}`\n\nType: `{var_type}`"

        if hasattr(analyzer, 'var_types') and word in analyzer.var_types:
            return f"**variable** `{word}`\n\nType: `{analyzer.var_types[word]}`"

        return None

    def _extract_qualified_name(self, line: str, col: int) -> str:
        """Extract the qualified identifier (with ::) at the given column."""
        if col >= len(line):
            return ""
        if not (line[col].isalnum() or line[col] == '_'):
            return ""

        end = col
        while end < len(line) and (line[end].isalnum() or line[end] == '_'):
            end += 1

        start = col
        while start > 0 and (line[start-1].isalnum() or line[start-1] == '_'):
            start -= 1

        full_name = line[start:end]

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
        import urllib.parse
        path = urllib.parse.unquote(path)
        return path
    return uri


def main():
    """Main entry point."""
    if not PYGLS_AVAILABLE:
        print("Error: pygls not available", file=sys.stderr)
        sys.exit(1)

    server = C5LanguageServer()
    server.start()


if __name__ == '__main__':
    main()
