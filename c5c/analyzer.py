import sys

class SemanticAnalyzer:
    def __init__(self, source_code=None, filename=None):
        self.errors = []
        self.warnings = []
        self.scopes = [{}] 
        self.var_locs = {}  # Track variable declaration locations
        self.func_locs = {}  # Track function declaration locations
        self.functions = {}
        self.structs = {}
        self.enums = {}
        self.used_vars = set()
        self.used_funcs = set(['main'])
        self.source_code = source_code
        self.source_lines = source_code.split('\n') if source_code else []
        self.filename = filename or "unknown"
        self.show_warnings = True
        self.library_funcs = set()  # Functions from library files (no dead code warnings)

        self.error_db = {
            "E001": ("Undefined symbol", "The identifier was not found in any visible scope."),
            "E002": ("Type Mismatch", "Incompatible types in assignment or binary operation."),
            "E003": ("Invalid 'void' type", "Variables cannot be of type void."),
            "E004": ("Division by Zero", "Static division by zero detected."),
            "E005": ("Function not declared", "Call only known functions."),
            "E006": ("Invalid Struct member", "The field does not exist in the structure definition."),
            "E007": ("Structure Redeclaration", "The struct name is already in use."),
            "E008": ("Enum not found", "The Enum name is invalid or was not declared."),
            "E009": ("Missing Entry Point", "Define a 'void main()' or 'int main()' function."),
            "E010": ("Function Redeclaration", "Global functions must have unique names."),
            "E011": ("Insufficient/Excessive Arguments", "The call does not match the function signature."),
            "E012": ("Invalid '.' access", "The dot operator only works on structs."),
            "E013": ("Invalid Void Return", "Void functions should not return values."),
            "E014": ("No Return Path", "Non-void function must return a value."),
            "E015": ("Redefined Symbol", "Name already declared in the current scope."),
            "E016": ("Invalid '::' access", "Namespace or Enum not found."),
            "E017": ("Illegal String Operation", "Strings only accept + and -."),
            "E018": ("Unknown Type", "The compiler does not recognize this type."),
            "E019": ("L-Value Error", "Left side of assignment must be writable."),
            "E021": ("Main Signature Error", "main() must return int or void."),
            "E041": ("Invalid main arguments", "main must have 0 or 2 arguments.")
        }

        self.warning_db = {
            "W001": ("Dead Code (Variable)", "Variable declared and never used."),
            "W002": ("Wasted Value", "Expression result will be discarded."),
            "W003": ("Unreachable Code", "Code after return/break."),
            "W004": ("Neutral Addition", "Redundant (+0/-0) operation."),
            "W005": ("Neutral Multiplication", "Redundant (*1//1) operation."),
            "W007": ("Narrowing conversion", "Possible data loss during float to int conversion."),
            "W008": ("Dead Code (Function)", "Local function declared and never called."),
            "W012": ("Empty Block", "Control statement without execution body.")
        }
    
    def _get_loc(self, node):
        """Extract location (line, col) from an AST node."""
        if node and isinstance(node, tuple) and len(node) >= 2:
            # Location is typically the last element
            loc = node[-1]
            if isinstance(loc, tuple) and len(loc) == 2:
                return loc
        return (1, 0)
    
    def _format_source_line(self, line, col):
        """Format a source line with error pointer."""
        if line < 1 or line > len(self.source_lines):
            return ""
        source_line = self.source_lines[line - 1]
        # Create pointer line
        pointer = ' ' * col + '^'
        return f">   {source_line}\n    {pointer}"
        
    def add_error(self, code, msg=None, loc=None):
        m, t = self.error_db.get(code, ("Error", "-"))
        if msg: m += f" [{msg}]"
        
        line, col = loc if loc else (1, 0)
        location_str = f"{self.filename}:{line}:{col}"
        source_context = self._format_source_line(line, col)
        
        error_msg = f"{location_str}: \033[91merror\033[0m: {m}\n{source_context}\n  \033[93m💡 Tip:\033[0m {t}"
        self.errors.append(error_msg)
        
    def add_warning(self, code, msg=None, loc=None):
        m, t = self.warning_db.get(code, ("WARNING", "-"))
        if msg: m += f" [{msg}]"
        
        line, col = loc if loc else (1, 0)
        location_str = f"{self.filename}:{line}:{col}"
        source_context = self._format_source_line(line, col)
        
        warning_msg = f"{location_str}: \033[93mwarning\033[0m: {m}\n{source_context}\n  \033[94m💡 Tip:\033[0m {t}"
        self.warnings.append(warning_msg)

    def analyze(self, ast, require_main=True, show_warnings=True):
        self.show_warnings = show_warnings
        self._scan_declarations(ast)
        
        if require_main and 'main' not in self.functions: self.add_error("E009")
            
        if isinstance(ast, list):
            for node in ast: self._analyze_node(node)
        else: self._analyze_node(ast)
        
        # Final checks - use stored variable locations
        for name in self.scopes[0]:
            if name not in self.used_vars and name not in self.functions:
                loc = self.var_locs.get(name, (1, 0))
                self.add_warning("W001", name, loc)
        
        for name, info in self.functions.items():
            is_extern = info[3]
            is_lib_func = name in self.library_funcs
            if name not in self.used_funcs and name != 'main' and not is_extern and not is_lib_func:
                loc = self.func_locs.get(name, (1, 0))
                self.add_warning("W008", name, loc)

        if self.errors:
            print(f"\n\033[91m🚨 C5 COMPILER: {len(self.errors)} ERROR(S) FOUND\033[0m")
            for e in sorted(list(set(self.errors))): print(e)
            sys.exit(1)
            
        if self.warnings and self.show_warnings:
            print(f"\n\033[93m⚠️  C5 COMPILER: {len(self.warnings)} QUALITY WARNING(S)\033[0m")
            for w in sorted(list(set(self.warnings))): print(w)

    def _get_type(self, node):
        if not node: return "void"
        tag = node[0]
        if tag == 'number': return "int"
        if tag == 'float': return "float"
        if tag == 'string': return "string"
        if tag == 'char': return "char"
        if tag == 'id':
            name = node[1]
            for scope in reversed(self.scopes):
                if name in scope: return scope[name]
        if tag == 'binop':
            op = node[1]
            left_ty = self._get_type(node[2])
            right_ty = self._get_type(node[3] if len(node) > 3 and not isinstance(node[3], tuple) else node[3])
            
            # Handle new AST structure with location
            right_node = node[3] if len(node) <= 4 or isinstance(node[3], tuple) else node[3]
            right_ty = self._get_type(right_node)
            
            if left_ty.endswith('*'):
                if right_ty == 'int' and op in ('+', '-'): return left_ty
                if right_ty.endswith('*') and op == '-': return 'int'
            elif right_ty.endswith('*'):
                if left_ty == 'int' and op == '+': return right_ty
            
            # Preserve signed/unsigned in binary operations
            # If either operand is unsigned, result is unsigned
            left_is_unsigned = left_ty.startswith('unsigned ')
            right_is_unsigned = right_ty.startswith('unsigned ')
            if left_is_unsigned or right_is_unsigned:
                # Get base type
                base_left = left_ty.split(' ', 1)[1] if left_is_unsigned else left_ty
                base_right = right_ty.split(' ', 1)[1] if right_is_unsigned else right_ty
                # Return unsigned version of left type
                if left_is_unsigned:
                    return left_ty
                else:
                    return f"unsigned {base_left}"
                
            return left_ty
        if tag == 'unary':
            op = node[1]
            sub_ty = self._get_type(node[2])
            if op == '&': return sub_ty + '*'
            if op == '*': return sub_ty[:-1] if sub_ty.endswith('*') else 'unknown'
            return sub_ty
        if tag == 'member_access':
            base_ty = self._get_type(node[1])
            # Handle pointer to struct (from array of structs)
            if base_ty.endswith('*'):
                struct_ty = base_ty[:-1]
                if struct_ty in self.structs:
                    for fty, fname in self.structs[struct_ty]:
                        if fname == node[2]: return fty
            if base_ty in self.structs:
                for fty, fname in self.structs[base_ty]:
                    if fname == node[2]: return fty
        if tag == 'arrow_access':
            base_ty = self._get_type(node[1])
            if base_ty.endswith('*'):
                struct_ty = base_ty[:-1]
                if struct_ty in self.structs:
                    for fty, fname in self.structs[struct_ty]:
                        if fname == node[2]: return fty
        if tag == 'array_access':
            base_ty = self._get_type(node[1])
            if base_ty.startswith('array<') and base_ty.endswith('>'):
                return base_ty[6:-1]
            return "unknown"
        if tag == 'call':
            target = node[1]
            if target[0] == 'member_access':
                method = target[2]
                base_ty = self._get_type(target[1])
                if base_ty.startswith('array<'):
                    if method == 'length': return 'int'
                    if method == 'pop':
                        return base_ty[6:-1]
                    return 'void'
            name = target[1] if target[0] == 'id' else f"{target[1]}::{target[2]}"
            return self.functions.get(name, ("int", 0, False, False))[0]
        return "unknown"

    def _analyze_node(self, node):
        if not node or not isinstance(node, tuple): return
        tag = node[0]
        loc = self._get_loc(node)
        
        if tag == 'var_decl':
            ty, name, init = node[1], node[2], node[3]
            if name in self.scopes[-1]: self.add_error("E015", name, loc)
            self.scopes[-1][name] = ty
            self.var_locs[name] = loc  # Store variable location
            if init: self._analyze_node(init)
        
        elif tag == 'pub_var':
            ty, name, init = node[1], node[2], node[3]
            # Checked in scan_declarations
            if init: self._analyze_node(init)
        
        elif tag == 'assign':
            left, right = node[1], node[2]
            self._analyze_node(left)
            self._analyze_node(right)
            l_ty, r_ty = self._get_type(left), self._get_type(right)
            if l_ty == 'int' and r_ty == 'float': self.add_warning("W007", loc=loc)

        elif tag == 'binop':
            op, left, right = node[1], node[2], node[3]
            self._analyze_node(left)
            self._analyze_node(right)
            if op == '/' and right[0] == 'number' and str(right[1]) == '0': self.add_error("E004", loc=loc)
            ty_l = self._get_type(left)
            if ty_l == 'string' and op not in ('+', '-'): self.add_error("E017", op, loc)
            if op in ('+', '-') and right[0] == 'number' and str(right[1]) == '0': self.add_warning("W004", loc=loc)

        elif tag == 'unary':
            self._analyze_node(node[2])

        elif tag == 'call':
            target = node[1]
            args = node[2]
            
            if target[0] == 'member_access':
                self._analyze_node(target[1])
                for a in args: self._analyze_node(a)
            else:
                name = target[1] if target[0] == 'id' else f"{target[1]}::{target[2]}"

                # Check if this is a function pointer variable (lambda)
                is_func_ptr = False
                if target[0] == 'id':
                    for scope in self.scopes:
                        if name in scope:
                            is_func_ptr = True
                            self.used_vars.add(name)
                            break
                
                if not is_func_ptr:
                    if name not in self.functions:
                        self.add_error("E005", name, loc)
                    else:
                        self.used_funcs.add(name)
                        ret, min_args, is_varargs, _ = self.functions[name]
                        if len(args) < min_args: self.add_error("E011", f"'{name}' expects at least {min_args}", loc)
                        elif not is_varargs and len(args) > min_args: self.add_error("E011", f"'{name}'", loc)
                for a in args: self._analyze_node(a)

        elif tag == 'func':
            self.scopes.append(dict(self.scopes[0]))
            for pty, pname in node[3]: self.scopes[-1][pname] = pty
            for s in node[4]: self._analyze_node(s)
            curr_scope = self.scopes.pop()
            for var in curr_scope:
                if var not in self.used_vars and var not in self.functions:
                    var_loc = self.var_locs.get(var, loc)
                    self.add_warning("W001", var, var_loc)

        elif tag == 'if_stmt':
            self._analyze_node(node[1])
            for s in node[2]: self._analyze_node(s)
            if node[3]:
                for s in node[3]: self._analyze_node(s)

        elif tag == 'id':
            name = node[1]
            found = False
            for scope in self.scopes:
                if name in scope:
                    found = True
                    break
            if not found: self.add_error("E001", name, loc)
            else: self.used_vars.add(name)
        
        elif tag == 'member_access':
            base_ty = self._get_type(node[1])
            # Allow member access on structs, pointers to structs (from array of structs), and arrays
            is_valid = base_ty in self.structs or base_ty.startswith('array<')
            # Also allow pointer to struct (returned from array access on struct arrays)
            if base_ty.endswith('*') and base_ty[:-1] in self.structs:
                is_valid = True
            if base_ty != 'unknown' and not is_valid:
                self.add_error("E012", base_ty, loc)
            self._analyze_node(node[1])

        elif tag == 'arrow_access':
            base_ty = self._get_type(node[1])
            if base_ty != 'unknown' and not base_ty.endswith('*'):
                self.add_error("E012", f"{base_ty} (not a pointer)", loc)
            self._analyze_node(node[1])

        elif tag == 'array_access':
            self._analyze_node(node[1])
            self._analyze_node(node[2])

        elif tag == 'foreach_stmt':
            # foreach (index_var, value_var in array_expr) { body }
            index_var, value_var, array_expr, body = node[1], node[2], node[3], node[4]
            
            # Analyze the array expression
            self._analyze_node(array_expr)
            
            # Get the element type from the array
            array_ty = self._get_type(array_expr)
            elem_ty = 'int'  # default
            if array_ty.startswith('array<') and array_ty.endswith('>'):
                elem_ty = array_ty[6:-1]
            
            # Add index and value variables to a new scope
            self.scopes.append({})
            self.scopes[-1][index_var] = 'int'
            self.scopes[-1][value_var] = elem_ty
            self.var_locs[index_var] = loc
            self.var_locs[value_var] = loc
            
            # Analyze body
            for s in body:
                self._analyze_node(s)
            
            # Pop scope
            self.scopes.pop()

        elif tag in ('expr_stmt', 'return_stmt', 'while_stmt', 'for_stmt', 'do_while_stmt'):
             for child in node[1:]:
                 if isinstance(child, (tuple, list)):
                     if isinstance(child, list):
                         for i in child: self._analyze_node(i)
                     else: self._analyze_node(child)
        
        elif tag == 'lambda':
            # Lambda expression: create a new scope for parameters and analyze body
            params, body = node[1], node[2]
            self.scopes.append({})
            for pty, pname in params:
                self.scopes[-1][pname] = pty
                self.var_locs[pname] = loc
            for s in body:
                self._analyze_node(s)
            self.scopes.pop()
        
        elif tag == 'init_list':
            # Initializer list: analyze all elements
            for elem in node[1]:
                self._analyze_node(elem)

    def _scan_declarations(self, ast):
        target = ast
        if isinstance(ast, tuple) and ast[0] == 'program': target = ast[1]
        for node in target:
            if not isinstance(node, tuple): continue
            loc = self._get_loc(node)
            if node[0] == 'func':
                if node[2] in self.functions: self.add_error("E010", node[2], loc)
                self.functions[node[2]] = (node[1], len(node[3]), False, False)
                self.func_locs[node[2]] = loc  # Store function location
            elif node[0] == 'extern':
                self.functions[node[2]] = (node[1], len(node[3]), node[4], True)
                self.func_locs[node[2]] = loc  # Store function location
            elif node[0] == 'struct_decl':
                self.structs[node[1]] = node[2]
            elif node[0] == 'enum_decl':
                self.enums[node[1]] = node[2]
            elif node[0] == 'pub_var':
                ty, name = node[1], node[2]
                if name in self.scopes[0]: self.add_error("E015", name, loc)
                self.scopes[0][name] = ty
                self.var_locs[name] = loc  # Store variable location
