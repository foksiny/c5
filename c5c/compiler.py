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

def _collect_macros(ast):
    """Collect all macro definitions from the AST."""
    macros = {}
    for node in ast:
        if isinstance(node, tuple) and node[0] == 'macro':
            _, name, params, body, _ = node
            macros[name] = (params, body)
    return macros

def _substitute_params(node, param_map, loc):
    """Substitute parameter names with argument expressions in an AST node."""
    if not isinstance(node, tuple):
        if isinstance(node, list):
            return [_substitute_params(n, param_map, loc) for n in node]
        return node
    
    tag = node[0]
    
    # If it's an identifier, check if it's a parameter
    if tag == 'id':
        name = node[1]
        if name in param_map:
            # Return a copy of the argument expression with updated location
            arg = param_map[name]
            return _update_loc(arg, loc)
        return node
    
    # Recursively process all children
    new_children = []
    for i, child in enumerate(node):
        if isinstance(child, (tuple, list)):
            new_children.append(_substitute_params(child, param_map, loc))
        else:
            new_children.append(child)
    
    return tuple(new_children)

def _update_loc(node, loc):
    """Update location information in an AST node recursively."""
    if not isinstance(node, tuple):
        if isinstance(node, list):
            return [_update_loc(n, loc) for n in node]
        return node
    
    # Process children first
    new_children = []
    for child in node[:-1] if len(node) > 1 else node:
        if isinstance(child, (tuple, list)):
            new_children.append(_update_loc(child, loc))
        else:
            new_children.append(child)
    
    # Check if last element is a location tuple
    if len(node) >= 2:
        last = node[-1]
        if isinstance(last, tuple) and len(last) == 2 and all(isinstance(x, int) for x in last):
            # Replace location
            return tuple(new_children) + (loc,)
    
    return tuple(new_children)

def _expand_macros(ast, macros):
    """Expand all macro calls in the AST."""
    if not isinstance(ast, tuple):
        if isinstance(ast, list):
            return [_expand_macros(node, macros) for node in ast]
        return ast
    
    tag = ast[0]
    
    # Check for macro call: call node with id target matching a macro name
    if tag == 'call':
        target = ast[1]
        args = ast[2]
        loc = ast[-1] if len(ast) > 3 and isinstance(ast[-1], tuple) else (1, 0)
        
        # Check if target is a simple identifier that matches a macro
        if isinstance(target, tuple) and target[0] == 'id':
            macro_name = target[1]
            if macro_name in macros:
                params, body = macros[macro_name]
                
                # Build parameter -> argument mapping
                param_map = {}
                for i, param in enumerate(params):
                    if i < len(args):
                        param_map[param] = args[i]
                
                # Substitute parameters in body
                expanded_body = _substitute_params(body, param_map, loc)
                
                # If body is a single expression statement, extract the expression
                if (isinstance(expanded_body, list) and len(expanded_body) == 1 and
                    isinstance(expanded_body[0], tuple) and expanded_body[0][0] == 'expr_stmt'):
                    return _expand_macros(expanded_body[0][1], macros)
                
                # Return the expanded body (could be multiple statements)
                return _expand_macros(expanded_body, macros)
    
    # Recursively process all children
    new_children = []
    for child in ast:
        if isinstance(child, (tuple, list)):
            new_children.append(_expand_macros(child, macros))
        else:
            new_children.append(child)
    
    return tuple(new_children)

def compile_file(filepath, include_paths=None, is_library=False):
    if include_paths is None: include_paths = []
    
    code = open(filepath).read()
    tokens = lex(code)
    parser = Parser(tokens)
    ast = parser.parse_program()
    
    dir_path = os.path.dirname(os.path.abspath(filepath))
    global_path = os.path.expanduser("~/.c5/include")
    
    new_ast = []
    library_funcs = set()  # Track functions from included headers
    library_vars = set()   # Track variables from included headers
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
                if isinstance(n, tuple):
                    tag = n[0]
                    l = list(n)
                    if tag in ('func', 'extern'):
                        l[2] = f"{namespace}::{l[2]}"
                        namespaced_ast.append(tuple(l))
                    elif tag in ('struct_decl', 'enum_decl', 'macro', 'type_decl'):
                        l[1] = f"{namespace}::{l[1]}"
                        namespaced_ast.append(tuple(l))
                    elif tag == 'pub_var':
                        l[2] = f"{namespace}::{l[2]}"
                        namespaced_ast.append(tuple(l))
                    else:
                        namespaced_ast.append(n)
                else:
                    namespaced_ast.append(n)
            # Collect library functions and variables from this include
            for n in namespaced_ast:
                if isinstance(n, tuple):
                    if n[0] in ('func', 'extern'):
                        library_funcs.add(n[2])
                    elif n[0] == 'pub_var':
                        library_vars.add(n[2])
            new_ast.extend(namespaced_ast)
        else:
            new_ast.append(node)
    
    # Collect and expand macros
    macros = _collect_macros(new_ast)
    expanded_ast = _expand_macros(new_ast, macros)
    
    # Remove macro definitions from AST after expansion
    final_ast = [node for node in expanded_ast if not (isinstance(node, tuple) and node[0] == 'macro')]
            
    from .analyzer import SemanticAnalyzer
    analyzer = SemanticAnalyzer(source_code=code, filename=filepath)
    analyzer.library_funcs = library_funcs
    analyzer.library_vars = library_vars
    analyzer.analyze(final_ast, require_main=not is_library, show_warnings=not is_library)

    # Strip location info before passing to optimizer/codegen
    stripped_ast = _strip_loc(final_ast)

    from .optimizer import Optimizer
    opt = Optimizer()
    optimized_ast = opt.optimize_ast(stripped_ast)

    cg = CodeGen(optimizer=opt)
    return cg.generate(optimized_ast)


def compile_files(filepaths, include_paths=None, is_library=False):
    """Compile multiple source files into a single assembly output.
    
    This is used for library compilation where implementation files (.c5)
    are compiled together with the main file.
    """
    if include_paths is None: include_paths = []
    
    combined_ast = []
    all_code = ""
    primary_file = filepaths[0]
    library_funcs = set()  # Track functions from non-primary files
    library_vars = set()   # Track variables from library files (no dead code warnings)
    
    for filepath in filepaths:
        code = open(filepath).read()
        all_code += f"\n// File: {filepath}\n" + code
        
        tokens = lex(code)
        parser = Parser(tokens)
        ast = parser.parse_program()
        
        dir_path = os.path.dirname(os.path.abspath(filepath))
        global_path = os.path.expanduser("~/.c5/include")
        
        # If this is not the primary file, track its functions as library functions
        is_primary = (filepath == primary_file)
        
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
                    if isinstance(n, tuple):
                        tag = n[0]
                        l = list(n)
                        if tag in ('func', 'extern'):
                            l[2] = f"{namespace}::{l[2]}"
                            namespaced_ast.append(tuple(l))
                        elif tag in ('struct_decl', 'enum_decl', 'macro', 'type_decl'):
                            l[1] = f"{namespace}::{l[1]}"
                            namespaced_ast.append(tuple(l))
                        elif tag == 'pub_var':
                            l[2] = f"{namespace}::{l[2]}"
                            namespaced_ast.append(tuple(l))
                        else:
                            namespaced_ast.append(n)
                    else:
                        namespaced_ast.append(n)
                # Collect library functions and variables from this include
                for n in namespaced_ast:
                    if isinstance(n, tuple):
                        if n[0] in ('func', 'extern'):
                            library_funcs.add(n[2])
                        elif n[0] == 'pub_var':
                            library_vars.add(n[2])
                combined_ast.extend(namespaced_ast)
            else:
                # Track functions and variables from non-primary files
                if not is_primary and isinstance(node, tuple):
                    if node[0] == 'func':
                        library_funcs.add(node[2])  # node[2] is the function name
                    elif node[0] == 'pub_var':
                        library_vars.add(node[2])  # node[2] is the variable name
                combined_ast.append(node)
    
    # Collect and expand macros
    macros = _collect_macros(combined_ast)
    expanded_ast = _expand_macros(combined_ast, macros)
    
    # Remove macro definitions from AST after expansion
    final_ast = [node for node in expanded_ast if not (isinstance(node, tuple) and node[0] == 'macro')]
            
    from .analyzer import SemanticAnalyzer
    analyzer = SemanticAnalyzer(source_code=all_code, filename=primary_file)
    analyzer.library_funcs = library_funcs
    analyzer.library_vars = library_vars
    analyzer.analyze(final_ast, require_main=not is_library, show_warnings=not is_library)

    # Strip location info before passing to optimizer/codegen
    stripped_ast = _strip_loc(final_ast)

    from .optimizer import Optimizer
    opt = Optimizer()
    optimized_ast = opt.optimize_ast(stripped_ast)

    cg = CodeGen(optimizer=opt)
    return cg.generate(optimized_ast)
