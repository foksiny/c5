import sys
import struct

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
        self.types = {}  # Type definitions (union/variant types)
        self.used_vars = set()
        self.used_funcs = set(['main'])
        self.source_code = source_code
        self.source_lines = source_code.split('\n') if source_code else []
        self.filename = filename or "unknown"
        self.show_warnings = True
        self.library_funcs = set()  # Functions from library files (no dead code warnings)
        self.library_vars = set()   # Variables from library files (no dead code warnings)
        self.break_context = []  # Stack to track if we're inside a loop or switch (for break statements)

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
            "E041": ("Invalid main arguments", "main must have 0 or 2 arguments."),
            "E042": ("Const Violation", "Cannot modify a const variable."),
            "E023": ("Integer Overflow", "Integer literal exceeds the range of the target type."),
        }

        self.warning_db = {
            "W001": ("Dead Code (Variable)", "Variable declared and never used."),
            "W002": ("Wasted Value", "Expression result will be discarded."),
            "W003": ("Unreachable Code", "Code after return/break."),
            "W004": ("Neutral Addition", "Redundant (+0/-0) operation."),
            "W005": ("Neutral Multiplication", "Redundant (*1//1) operation."),
            "W006": ("Narrowing Float Conversion", "Possible data loss during float64 to float32 conversion."),
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
        
        error_msg = f"{location_str}: \033[91merror\033[0m: {m}\n{source_context}\n  \033[93mTip:\033[0m {t}"
        self.errors.append(error_msg)
        
    def add_warning(self, code, msg=None, loc=None):
        m, t = self.warning_db.get(code, ("WARNING", "-"))
        if msg: m += f" [{msg}]"
        
        line, col = loc if loc else (1, 0)
        location_str = f"{self.filename}:{line}:{col}"
        source_context = self._format_source_line(line, col)
        
        warning_msg = f"{location_str}: \033[93mwarning\033[0m: {m}\n{source_context}\n  \033[94mTip:\033[0m {t}"
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
            if name not in self.used_vars and name not in self.functions and name not in self.library_vars:
                loc = self.var_locs.get(name, (1, 0))
                self.add_warning("W001", name, loc)
        
        for name, info in self.functions.items():
            is_extern = info[3]
            is_lib_func = name in self.library_funcs
            if name not in self.used_funcs and name != 'main' and not is_extern and not is_lib_func:
                loc = self.func_locs.get(name, (1, 0))
                self.add_warning("W008", name, loc)

        if self.errors:
            print(f"\n\033[91mC5 COMPILER: {len(self.errors)} ERROR(S) FOUND\033[0m")
            for e in sorted(list(set(self.errors))): print(e)
            sys.exit(1)
            
        if self.warnings and self.show_warnings:
            print(f"\n\033[93mC5 COMPILER: {len(self.warnings)} QUALITY WARNING(S)\033[0m")
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
                if name in scope:
                    ty = scope[name]
                    # Strip const modifier for type checking
                    if ty.startswith('const '):
                        ty = ty[6:]  # Remove "const " prefix
                    return ty
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
        if tag == 'namespace_access':
            name = f"{node[1]}::{node[2]}"
            # Try global scope (where namespaced variables are)
            if name in self.scopes[0]: return self.scopes[0][name]
            # Try enums
            if node[1] in self.enums: return node[1]
            # Try functions (for function pointers)
            if name in self.functions: return self.functions[name][0]
            return "unknown"
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
            # Handle [] on char* or string types - returns char
            if base_ty == 'char*' or base_ty == 'string':
                return 'char'
            # Handle [] on other pointer types - returns the pointed-to type
            if base_ty.endswith('*'):
                return base_ty[:-1]
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
            # Handle built-in c_str() function
            if name == 'c_str':
                return 'char*'
            return self.functions.get(name, ("int", 0, False, False))[0]
        return "unknown"

    # Helper methods for type checking
    def _is_integer_type(self, ty):
        """Check if a type string represents an integer type."""
        # Strip const modifier if present
        if ty.startswith('const '):
            ty = ty[6:]
        if ty in ('int', 'char'):
            return True
        if ty.startswith('unsigned ') or ty.startswith('signed '):
            base = ty.split(' ', 1)[1]
            return base in ('int', 'char') or base.startswith('int<')
        if ty.startswith('int<') and ty.endswith('>'):
            return True
        return False

    def _is_float_type(self, ty):
        """Check if a type is a floating-point type."""
        # Strip const modifier if present
        if ty.startswith('const '):
            ty = ty[6:]
        return ty in ('float', 'float<32>', 'float<64>')

    def _normalize_type(self, ty):
        """Normalize type aliases to canonical forms."""
        if ty == 'int':
            return 'int<64>'
        if ty == 'float':
            return 'float<64>'
        return ty

    def _types_compatible(self, target_type, source_type):
        """Check if source_type can be assigned to target_type."""
        # If target is a union type, check if source matches any member
        if target_type in self.types:
            for mem_type in self.types[target_type]:
                if self._types_compatible(mem_type, source_type):
                    return True
            return False
        # If source is a union type, cannot assign to a non-union
        if source_type in self.types:
            return False
        # Normalize and compare
        t_norm = self._normalize_type(target_type)
        s_norm = self._normalize_type(source_type)
        return t_norm == s_norm

    def _int_literal_fits(self, ty, value):
        """Check if an integer literal fits in the given type without adding error."""
        # Strip const modifier if present
        if ty.startswith('const '):
            ty = ty[6:]
        signed = True
        base_ty = ty
        if ty.startswith('unsigned '):
            signed = False
            base_ty = ty[9:]
        elif ty.startswith('signed '):
            signed = True
            base_ty = ty[7:]
        if base_ty == 'int':
            bits = 64
        elif base_ty == 'char':
            bits = 8
        elif base_ty.startswith('int<') and base_ty.endswith('>'):
            try:
                bits = int(base_ty[4:-1])
            except:
                return False
        else:
            return False
        if signed:
            min_val = -(1 << (bits - 1))
            max_val = (1 << (bits - 1)) - 1
        else:
            min_val = 0
            max_val = (1 << bits) - 1
        return min_val <= value <= max_val

    def _check_int_literal_against_type(self, ty, value, loc):
        """Check integer literal against a type, handling unions."""
        if ty in self.types:
            # Union type: check if any integer member can hold the value
            members = self.types[ty]
            int_members = [m for m in members if self._is_integer_type(m)]
            if not int_members:
                self.add_error("E002", f"Integer literal cannot initialize union {ty} (no integer members)", loc)
                return
            fits = any(self._int_literal_fits(m, value) for m in int_members)
            if not fits:
                self.add_error("E023", f"Integer literal {value} does not fit in any integer member of {ty}", loc)
        elif self._is_integer_type(ty):
            self._check_int_literal_range(ty, value, loc)
        else:
            self.add_error("E002", f"Integer literal cannot initialize type {ty}", loc)

    def _float_literal_exact_float32(self, val):
        """Check if a float value can be exactly represented as float32."""
        try:
            packed = struct.pack('f', val)
            restored = struct.unpack('f', packed)[0]
            return val == restored
        except:
            return False

    def _check_float_literal_against_type(self, ty, value, loc):
        """Check float literal against a type, handling exact representation for float<32>."""
        # Strip const modifier if present
        base_ty = ty
        if ty.startswith('const '):
            base_ty = ty[6:]
        if ty in self.types:
            # Union type: check if any member can accept the float
            members = self.types[ty]
            fits = False
            for mem in members:
                # Strip const from member types for comparison
                mem_clean = mem[6:] if mem.startswith('const ') else mem
                if mem_clean == 'float' or mem_clean == 'float<64>':
                    fits = True
                    break
                if mem_clean == 'float<32>':
                    if self._float_literal_exact_float32(value):
                        fits = True
                        break
            if not fits:
                self.add_error("E002", f"Float literal {value} cannot initialize union {ty}", loc)
        else:
            if base_ty == 'float' or base_ty == 'float<64>':
                # Always okay
                return
            if base_ty == 'float<32>':
                if not self._float_literal_exact_float32(value):
                    self.add_error("E002", f"Float literal {value} cannot be exactly represented in float<32>", loc)
            else:
                self.add_error("E002", f"Float literal cannot initialize type {ty}", loc)

    def _eval_constant_int(self, node):
        """Evaluate an expression to a constant integer if possible."""
        if not node or not isinstance(node, tuple):
            return None
        tag = node[0]
        if tag == 'number':
            # Ensure it's an integer, not a float or char
            if isinstance(node[1], int):
                return node[1]
            return None
        elif tag == 'binop':
            left = self._eval_constant_int(node[2])
            right = self._eval_constant_int(node[3])
            if left is None or right is None:
                return None
            op = node[1]
            try:
                if op == '+': return left + right
                if op == '-': return left - right
                if op == '*': return left * right
                if op == '/': return left // right  # integer division
                if op == '%': return left % right
                if op == '<<': return left << right
                if op == '>>': return left >> right
                if op == '&': return left & right
                if op == '|': return left | right
                if op == '^': return left ^ right
            except Exception:
                return None
            return None
        return None

    def _analyze_node(self, node):
        if not node or not isinstance(node, tuple): return
        tag = node[0]
        loc = self._get_loc(node)
        
        if tag == 'var_decl':
            ty, name, init = node[1], node[2], node[3]
            if name in self.scopes[-1]: self.add_error("E015", name, loc)
            self.scopes[-1][name] = ty
            self.var_locs[name] = loc  # Store variable location
            if init:
                self._analyze_node(init)
                if init[0] == 'init_list':
                    # Struct or array initializer
                    if ty in self.structs:
                        fields = self.structs[ty]  # list of (field_type, field_name)
                        elements = init[1]
                        for i, elem in enumerate(elements):
                            if i >= len(fields):
                                self.add_error("E015", f"too many initializers for struct {ty}", loc)
                                break
                            field_type = fields[i][0]
                            # Check element compatibility
                            if elem[0] == 'number' and isinstance(elem[1], int):
                                self._check_int_literal_against_type(field_type, elem[1], loc)
                            elif elem[0] == 'float':
                                self._check_float_literal_against_type(field_type, elem[1], loc)
                            else:
                                elem_type = self._get_type(elem)
                                if not self._types_compatible(field_type, elem_type):
                                    self.add_error("E002", f"Cannot initialize field of type {field_type} with {elem_type}", loc)
                    # TODO: array initializer type checking
                elif init[0] == 'lambda':
                    # Lambda initializer: skip type check (the variable's type is the lambda's return type)
                    # The lambda body will be analyzed separately.
                    pass
                elif init[0] == 'number' and isinstance(init[1], int):
                    self._check_int_literal_against_type(ty, init[1], loc)
                elif init[0] == 'float':
                    self._check_float_literal_against_type(ty, init[1], loc)
                elif init[0] == 'binop':
                    const_val = self._eval_constant_int(init)
                    if const_val is not None:
                        self._check_int_literal_against_type(ty, const_val, loc)
                    else:
                        init_type = self._get_type(init)
                        if not self._types_compatible(ty, init_type):
                            self.add_error("E002", f"Cannot initialize {ty} with {init_type}", loc)
                else:
                    init_type = self._get_type(init)
                    if not self._types_compatible(ty, init_type):
                        self.add_error("E002", f"Cannot initialize {ty} with {init_type}", loc)
        
        elif tag == 'pub_var':
            ty, name, init = node[1], node[2], node[3]
            # Checked in scan_declarations
            if init: self._analyze_node(init)
        
        elif tag == 'assign':
            left, right = node[1], node[2]
            self._analyze_node(left)
            self._analyze_node(right)
            l_ty, r_ty = self._get_type(left), self._get_type(right)
            # Check integer literal range/type
            if right[0] == 'number' and isinstance(right[1], int):
                self._check_int_literal_against_type(l_ty, right[1], loc)
            elif right[0] == 'float':
                self._check_float_literal_against_type(l_ty, right[1], loc)
            else:
                # For non-literals, require type compatibility
                if not self._types_compatible(l_ty, r_ty):
                    self.add_error("E002", f"Cannot assign {r_ty} to {l_ty}", loc)

            # Check if left-hand side is a const variable
            if left[0] == 'id':
                name = left[1]
                # Check all scopes for the variable
                for scope in self.scopes:
                    if name in scope:
                        var_type = scope[name]
                        if var_type.startswith('const '):
                            self.add_error("E042", f"'{name}' is const and cannot be modified", loc)
                        break

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
                    # c_str() is a built-in function
                    if name == 'c_str':
                        pass  # Built-in function, no error
                    elif name not in self.functions:
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
                if var not in self.used_vars and var not in self.functions and var not in self.library_vars:
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
        
        elif tag == 'namespace_access':
            base, name = node[1], node[2]
            namespaced_name = f"{base}::{name}"
            found = False
            # Check for namespaced variables in global scope
            if namespaced_name in self.scopes[0]:
                found = True
                self.used_vars.add(namespaced_name)
            # Check for enums
            elif base in self.enums or namespaced_name in self.enums:
                found = True
            # Check for functions (for function pointers)
            elif namespaced_name in self.functions:
                found = True
                self.used_funcs.add(namespaced_name)
            
            if not found:
                self.add_error("E016", namespaced_name, loc)
        
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
            
            # Analyze body within break context
            self.break_context.append('loop')
            for s in body:
                self._analyze_node(s)
            self.break_context.pop()
            
            # Pop scope
            self.scopes.pop()

        elif tag in ('expr_stmt', 'return_stmt'):
            for child in node[1:]:
                if isinstance(child, (tuple, list)):
                    if isinstance(child, list):
                        for i in child: self._analyze_node(i)
                    else: self._analyze_node(child)
        
        elif tag == 'while_stmt':
            # while (cond) body
            self._analyze_node(node[1])  # condition
            self.break_context.append('loop')
            for s in node[2]:  # body
                self._analyze_node(s)
            self.break_context.pop()
            
        elif tag == 'for_stmt':
            # for (init; cond; inc) body
            self._analyze_node(node[1])  # init
            self.break_context.append('loop')
            self._analyze_node(node[2])  # condition
            self._analyze_node(node[3])  # increment
            for s in node[4]:  # body
                self._analyze_node(s)
            self.break_context.pop()
            
        elif tag == 'do_while_stmt':
            # do body while (cond)
            self.break_context.append('loop')
            for s in node[1]:  # body
                self._analyze_node(s)
            self.break_context.pop()
            self._analyze_node(node[2])  # condition
            
        elif tag == 'switch_stmt':
            # switch (cond) { cases }
            cond = node[1]
            cases = node[2]
            default_body = node[3]
            # Analyze switch condition
            self._analyze_node(cond)
            # Check that condition type is integer-like (int, char, enum, or signed/unsigned variants)
            cond_ty = self._get_type(cond)
            if cond_ty not in ('int', 'char') and not cond_ty.startswith('int<') and not cond_ty.startswith('unsigned ') and not cond_ty.startswith('signed ') and cond_ty not in self.enums:
                self.add_error("E002", f"switch condition must be integer or enum type, not {cond_ty}", loc)
            # Track case values to detect duplicates
            case_values = set()
            # Analyze each case
            for case in cases:
                # case is ('case', case_val, body, loc)
                case_val = case[1]
                case_body = case[2]
                case_loc = case[3]
                # Try to evaluate case value at compile time if it's a constant
                if case_val[0] in ('number', 'char'):
                    val = case_val[1]
                    # Check if this value already appeared
                    if val in case_values:
                        self.add_error("E015", f"duplicate case value {val}", case_loc)
                    else:
                        case_values.add(val)
                elif case_val[0] == 'id':
                    # Could be an enum value - check if it's in an enum
                    name = case_val[1]
                    found = False
                    for scope in self.scopes:
                        if name in scope:
                            # It's a variable, not a constant - can't validate at compile time
                            # We could try to see if it's an enum constant
                            found = True
                            break
                    if not found:
                        # Check if it's a namespaced enum access like Color::RED
                        if case_val[0] == 'namespace_access':
                            # Already handled as namespace_access node
                            pass
                        # We can't fully validate enum values at compile time without constant evaluation
                        # For now, we'll allow it and trust the programmer
                # Analyze case body within switch break context
                self.break_context.append('switch')
                for stmt in case_body:
                    self._analyze_node(stmt)
                self.break_context.pop()
            # Analyze default body if present
            if default_body:
                self.break_context.append('switch')
                for stmt in default_body:
                    self._analyze_node(stmt)
                self.break_context.pop()
                
        elif tag == 'break_stmt':
            # break; must be inside a loop or switch
            if not self.break_context:
                self.add_error("E999", "break statement not inside a loop or switch", loc)
            # break is valid - no further checks needed
            
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

    def _check_int_literal_range(self, ty, value, loc):
        """Check if an integer literal fits within the range of the given type."""
        # Handle signed/unsigned modifiers
        signed = True
        base_ty = ty
        if ty.startswith('unsigned '):
            signed = False
            base_ty = ty[9:]  # strip 'unsigned '
        elif ty.startswith('signed '):
            signed = True
            base_ty = ty[7:]  # strip 'signed '
        # Determine bit width
        if base_ty == 'int':
            bits = 64
        elif base_ty == 'char':
            bits = 8
        elif base_ty.startswith('int<') and base_ty.endswith('>'):
            try:
                bits = int(base_ty[4:-1])
            except:
                return  # Invalid format, skip
        else:
            return  # Not an integer type with width
        # Compute min and max
        if signed:
            min_val = -(1 << (bits - 1))
            max_val = (1 << (bits - 1)) - 1
        else:
            min_val = 0
            max_val = (1 << bits) - 1
        if value < min_val or value > max_val:
            self.add_error("E023", f"Value {value} does not fit in {ty} (range {min_val}..{max_val})", loc)

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
            elif node[0] == 'type_decl':
                ty_name = node[1]
                if ty_name in self.types: self.add_error("E015", ty_name, loc)
                self.types[ty_name] = node[2]  # Store list of allowed types
            elif node[0] == 'pub_var':
                ty, name = node[1], node[2]
                if name in self.scopes[0]: self.add_error("E015", name, loc)
                self.scopes[0][name] = ty
                self.var_locs[name] = loc  # Store variable location
