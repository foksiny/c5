import os
from .lexer import lex
from .parser import Parser
from .codegen import CodeGen

def _strip_loc(node):
    """Recursively strip location info from AST nodes for codegen/optimizer."""
    if not isinstance(node, tuple):
        if isinstance(node, list):
            return [_strip_loc(n) for n in node]
        return node
    # Remove last element if it's a location tuple (line, col)
    if len(node) >= 2:
        last = node[-1]
        if isinstance(last, tuple) and len(last) == 2 and all(isinstance(x, int) for x in last):
            # This looks like a location tuple, strip it
            node = node[:-1]
    # Recursively process children
    return tuple(_strip_loc(child) for child in node)

def compile_file(filepath, include_paths=None):
    if include_paths is None: include_paths = []
    
    code = open(filepath).read()
    tokens = lex(code)
    parser = Parser(tokens)
    ast = parser.parse_program()
    
    dir_path = os.path.dirname(os.path.abspath(filepath))
    global_path = os.path.expanduser("~/.c5/include")
    
    new_ast = []
    for node in ast:
        if node[0] == 'include':
            fname = node[1]
            inc_list = include_paths if include_paths else []
            search_paths = [dir_path] + inc_list + [
                os.path.join(dir_path, '..', 'c5include'),
                os.path.join(os.getcwd(), 'c5include'),
                global_path
            ]
            inc_path = None
            for p in search_paths:
                fullpath = os.path.join(p, fname)
                if os.path.exists(fullpath):
                    inc_path = fullpath
                    break
            if not inc_path:
                raise Exception(f"Include not found: {fname}")
            
            inc_code = open(inc_path).read()
            inc_tokens = lex(inc_code)
            inc_ast = Parser(inc_tokens).parse_program()
            
            # Auto-namespace based on filename (e.g., std.c5h -> std::)
            namespace = os.path.splitext(fname)[0]
            namespaced_ast = []
            for n in inc_ast:
                if isinstance(n, tuple) and n[0] in ('func', 'extern'):
                    l = list(n)
                    l[2] = f"{namespace}::{l[2]}"
                    namespaced_ast.append(tuple(l))
                else:
                    namespaced_ast.append(n)
            new_ast.extend(namespaced_ast)
        else:
            new_ast.append(node)
            
    from .analyzer import SemanticAnalyzer
    analyzer = SemanticAnalyzer(source_code=code, filename=filepath)
    analyzer.analyze(new_ast)

    # Strip location info before passing to optimizer/codegen
    stripped_ast = _strip_loc(new_ast)

    from .optimizer import Optimizer
    opt = Optimizer()
    optimized_ast = opt.optimize_ast(stripped_ast)

    cg = CodeGen(optimizer=opt)
    return cg.generate(optimized_ast)
