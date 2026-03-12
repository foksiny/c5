import sys
import os
import json
import re

# Redirect stdout to stderr
original_stdout = sys.stdout
sys.stdout = sys.stderr

# Add C5 compiler to sys.path
sys.path.append(os.path.expanduser("~/projects/c5"))

try:
    from c5c.lexer import lex
    from c5c.parser import Parser
    from c5c.analyzer import SemanticAnalyzer
    from c5c.compiler import _process_includes
    from c5c.main import parse_build_file
except ImportError:
    pass

def log(msg):
    sys.stderr.write(f"LOG: {msg}\n")
    sys.stderr.flush()

# Legend for semantic tokens
TOKEN_TYPES = ["type", "struct", "enum", "function", "namespace"]
TOKEN_MODS = []

class LSPAnalyzer(SemanticAnalyzer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lsp_diagnostics = []
        self.semantic_tokens = []
        self.symbols = {} # (line, col) -> info string
        self.func_signatures = {} # name -> (ret_ty, params)
        self.symbol_types = {}
        self.macros = {} # name -> params
    
    def add_error(self, code, msg=None, loc=None):
        m, _ = self.error_db.get(code, ("Error", "-"))
        if msg: m += f" [{msg}]"
        line, col = loc if loc else (1, 0)
        self.lsp_diagnostics.append({
            "range": {
                "start": {"line": max(0, line - 1), "character": col},
                "end": {"line": max(0, line - 1), "character": col + 5}
            },
            "message": f"{code}: {m}",
            "severity": 1
        })
        self.errors.append(m)

    def add_warning(self, code, msg=None, loc=None):
        m, _ = self.warning_db.get(code, ("Warning", "-"))
        if msg: m += f" [{msg}]"
        line, col = loc if loc else (1, 0)
        self.lsp_diagnostics.append({
            "range": {
                "start": {"line": max(0, line - 1), "character": col},
                "end": {"line": max(0, line - 1), "character": col + 5}
            },
            "message": f"{code}: {m}",
            "severity": 2
        })
        self.warnings.append(m)

    def _analyze_node(self, node):
        if not isinstance(node, tuple): return
        tag = node[0]
        if tag == 'var_decl':
            self.symbol_types[node[2]] = node[1]
        elif tag == 'foreach':
            self.symbol_types[node[1]] = 'int'
        elif tag == 'try_catch_stmt':
            self.symbol_types[node[2]] = 'string'
        elif tag == 'call':
            # Check if it's a macro call to avoid E005: Function not declared
            func_node = node[1]
            if isinstance(func_node, tuple) and func_node[0] == 'id':
                name = func_node[1]
                if name in self.macros:
                    # It's a macro, just analyze arguments
                    for arg in node[2]:
                        self._analyze_node(arg)
                    return
            elif isinstance(func_node, tuple) and func_node[0] == 'namespace_access':
                # Handle namespaced macros if any
                base = func_node[1]
                name = func_node[2]
                if isinstance(base, str):
                    full_name = f"{base}::{name}"
                    if full_name in self.macros:
                        for arg in node[2]:
                            self._analyze_node(arg)
                        return
        super()._analyze_node(node)

    def analyze(self, ast, require_main=True, show_warnings=True):
        self.show_warnings = show_warnings
        self._record_signatures(ast)
        self._scan_declarations(ast)
        for name, ty in self.scopes[0].items():
            self.symbol_types[name] = ty
        for node in ast:
            self._analyze_node(node)
            self._collect_tokens_and_symbols(node)
        if require_main and 'main' not in self.functions:
            self.add_error("E009")
        return self.errors, self.warnings

    def _record_signatures(self, ast):
        if not isinstance(ast, list): return
        for node in ast:
            if isinstance(node, tuple):
                if node[0] in ('func', 'extern'):
                    self.func_signatures[node[2]] = (node[1], node[3])
                    for pty, pname in node[3]: self.symbol_types[pname] = pty
                elif node[0] == 'macro':
                    self.macros[node[1]] = node[2]

    def _collect_tokens_and_symbols(self, node):
        if not isinstance(node, tuple):
            if isinstance(node, list):
                for n in node: self._collect_tokens_and_symbols(n)
            return
        tag = node[0]
        loc = self._get_loc(node)
        line, col = loc[0]-1, loc[1]

        if tag == 'id':
            self._process_symbol(node[1], line, col, len(node[1]))
        elif tag == 'namespace_access':
            # node: ('namespace_access', base, name, loc)
            base = node[1]
            name = node[2]
            if isinstance(base, str):
                full_name = f"{base}::{name}"
                self.semantic_tokens.append((line, col, len(base), 4)) # namespace index
                actual_col = col + len(base) + 2
                self._process_symbol(full_name, line, actual_col, len(name), base_col=col, base_len=len(base))
            elif isinstance(base, tuple):
                # Handle nested namespace access if any
                pass
        elif tag == 'func':
            ret, name, params = node[1], node[2], node[3]
            param_str = ", ".join([f"{pty} {pname}" for pty, pname in params])
            info = f"{ret} {name}({param_str})"
            self._apply_info_to_source(name, line, col, info, 3)
        elif tag == 'macro':
            name, params = node[1], node[2]
            param_str = ", ".join(params)
            info = f"macro {name}({param_str})"
            self._apply_info_to_source(name, line, col, info, 3)
        elif tag == 'struct_decl':
            name, fields = node[1], node[2]
            field_str = "\n".join([f"    {fty} {fname};" for fty, fname in fields])
            info = f"struct {name} {{\n{field_str}\n}};"
            self._apply_info_to_source(name, line, col, info, 1)
        elif tag == 'enum_decl':
            name, variants = node[1], node[2]
            variant_str = ", ".join(variants)
            info = f"enum {name} {{ {variant_str} }};"
            self._apply_info_to_source(name, line, col, info, 2)
        elif tag == 'type_decl':
            name, types = node[1], node[2]
            type_str = ", ".join(types)
            info = f"type {name} {{ {type_str} }};"
            self._apply_info_to_source(name, line, col, info, 0)
        elif tag in ('var_decl', 'pub_var'):
            ty, name = node[1], node[2]
            info = f"{ty} {name}"
            self._apply_info_to_source(name, line, col, info)

        for child in node:
            if isinstance(child, (tuple, list)):
                self._collect_tokens_and_symbols(child)

    def _apply_info_to_source(self, name, line, col, info, t_idx=None):
        source_line = self.source_lines[line] if line < len(self.source_lines) else ""
        # Search for the name starting from col
        # Use a regex that only matches the name as a whole word
        match = re.search(r'\b' + re.escape(name.split('::')[-1]) + r'\b', source_line[col:])
        if match:
            actual_col = col + match.start()
            if t_idx is not None: self.semantic_tokens.append((line, actual_col, len(name), t_idx))
            for i in range(len(name)): self.symbols[(line, actual_col + i)] = info

    def _process_symbol(self, full_name, line, col, length, base_col=None, base_len=0):
        t_idx, info = -1, None
        
        # Check for user-defined types (including namespaced ones)
        if full_name in self.structs:
            t_idx, fields = 1, self.structs[full_name]
            field_str = "\n".join([f"    {fty} {fname};" for fty, fname in fields])
            info = f"struct {full_name} {{\n{field_str}\n}};"
        elif full_name in self.enums:
            t_idx, variants = 2, self.enums[full_name]
            info = f"enum {full_name} {{ {', '.join(variants)} }};"
        elif full_name in self.types:
            t_idx, types = 0, self.types[full_name]
            info = f"type {full_name} {{ {', '.join(types)} }};"
        elif full_name in self.func_signatures:
            t_idx, (ret, params) = 3, self.func_signatures[full_name]
            param_str = ", ".join([f"{pty} {pname}" for pty, pname in params])
            info = f"{ret} {full_name}({param_str})"
        elif full_name in self.macros:
            t_idx, params = 3, self.macros[full_name]
            param_str = ", ".join(params)
            info = f"macro {full_name}({param_str})"
        elif full_name in self.symbol_types:
            info = f"{self.symbol_types[full_name]} {full_name}"
        
        # Check for enum variants (e.g., Enum::Variant)
        if not info and '::' in full_name:
            base, member = full_name.rsplit('::', 1)
            if base in self.enums and member in self.enums[base]:
                info = f"enum variant {full_name}"
        
        if t_idx != -1: self.semantic_tokens.append((line, col, length, t_idx))
        if info:
            for i in range(length): self.symbols[(line, col + i)] = info
            if base_col is not None:
                # Set symbols for the namespace part as well
                for i in range(base_len + 2): self.symbols[(line, base_col + i)] = info

def send_response(id, result):
    _send({"jsonrpc": "2.0", "id": id, "result": result})

def send_notification(method, params):
    _send({"jsonrpc": "2.0", "method": method, "params": params})

def _send(msg):
    encoded = json.dumps(msg)
    original_stdout.write(f"Content-Length: {len(encoded)}\r\n\r\n{encoded}")
    original_stdout.flush()

def find_project_root(current_path):
    dir_path = os.path.dirname(current_path)
    while dir_path and dir_path != "/":
        if os.path.exists(os.path.join(dir_path, "build.c5b")): return dir_path
        dir_path = os.path.dirname(dir_path)
    return os.path.dirname(current_path)

ANALYZER_CACHE = {}

def get_analyzer(code, filename):
    tokens = lex(code)
    parser = Parser(tokens)
    ast = parser.parse_program()
    dir_path = os.path.dirname(os.path.abspath(filename))
    root_path = find_project_root(filename)
    global_path = os.path.expanduser("~/.c5/include")
    new_ast, lib_funcs, lib_vars, _ = _process_includes(
        ast, dir_path, [], global_path, current_file_path=os.path.abspath(filename)
    )
    analyzer = LSPAnalyzer(source_code=code, filename=filename)
    analyzer.library_funcs, analyzer.library_vars = lib_funcs, lib_vars
    analyzer.analyze(new_ast, require_main=False)
    ANALYZER_CACHE[filename] = analyzer
    return analyzer, new_ast

def encode_tokens(tokens):
    tokens.sort()
    encoded, last_line, last_char = [], 0, 0
    for line, char, length, t_idx in tokens:
        line_delta = line - last_line
        char_delta = char if line_delta > 0 else char - last_char
        encoded.extend([line_delta, char_delta, length, t_idx, 0])
        last_line, last_char = line, char
    return encoded

def main():
    while True:
        line = sys.stdin.readline()
        if not line: break
        if line.startswith("Content-Length:"):
            try:
                length = int(line.split(":")[1].strip())
                sys.stdin.readline()
                content = sys.stdin.read(length)
                msg = json.loads(content)
                method, params, msg_id = msg.get("method"), msg.get("params"), msg.get("id")
                if method == "initialize":
                    send_response(msg_id, {"capabilities": {"textDocumentSync": 1, "hoverProvider": True, "semanticTokensProvider": {"legend": {"tokenTypes": TOKEN_TYPES, "tokenModifiers": TOKEN_MODS}, "full": True}}})
                elif method == "textDocument/hover":
                    uri, pos = params["textDocument"]["uri"], params["position"]
                    filename = uri.replace("file://", "")
                    if filename.startswith("/") and os.name == 'nt': filename = filename[1:]
                    analyzer = ANALYZER_CACHE.get(filename)
                    if analyzer:
                        info = analyzer.symbols.get((pos["line"], pos["character"]))
                        if info: send_response(msg_id, {"contents": {"kind": "markdown", "value": f"```c5\n{info}\n```"}})
                        else: send_response(msg_id, None)
                    else: send_response(msg_id, None)
                elif method == "textDocument/semanticTokens/full":
                    uri = params["textDocument"]["uri"]
                    filename = uri.replace("file://", "")
                    if filename.startswith("/") and os.name == 'nt': filename = filename[1:]
                    analyzer = ANALYZER_CACHE.get(filename)
                    if not analyzer and os.path.exists(filename):
                        with open(filename, 'r') as f: analyzer, _ = get_analyzer(f.read(), filename)
                    if analyzer: send_response(msg_id, {"data": encode_tokens(analyzer.semantic_tokens)})
                    else: send_response(msg_id, {"data": []})
                elif method in ("textDocument/didOpen", "textDocument/didChange", "textDocument/didSave"):
                    doc = params["textDocument"]
                    uri, text = doc["uri"], doc.get("text")
                    if text is None and "contentChanges" in params: text = params["contentChanges"][0]["text"]
                    if text is not None:
                        filename = uri.replace("file://", "")
                        if filename.startswith("/") and os.name == 'nt': filename = filename[1:]
                        analyzer, _ = get_analyzer(text, filename)
                        send_notification("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": analyzer.lsp_diagnostics})
            except Exception as e: log(f"Loop error: {str(e)}")

if __name__ == "__main__":
    main()
