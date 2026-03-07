class CodeGen:
    def __init__(self, optimizer=None, try_errors_map=None):
        self.optimizer = optimizer
        self.rodata = []
        self.text = []
        self.string_literals = {}
        self.str_count = 0
        self.float_literals = {}
        self.float_count = 0
        self.extern_funcs = {}
        self.func_signatures = {}
        self.structs = {}
        self.enums = {}
        self.types = {}  # Type definitions (union/variant types)
        self.local_vars = {}
        self.local_var_offset = 0
        self.label_count = 0
        self.global_vars = {}
        self.data = []
        self.uses_str_add = False
        self.uses_str_sub = False
        self.uses_str_replace = False
        self.lambda_count = 0
        self.lambda_funcs = []  # Store lambda function definitions
        self.break_targets = []  # Stack of break jump targets (for loops and switches)
        self.try_errors_map = try_errors_map or {}  # Map from try_catch loc to list of errors
        self.catch_param_counter = 0  # For generating unique catch parameter names
        self.int_format_label = None  # For integer-to-string conversion format
        self._current_ast = [] # Current AST being generated
        self.func_has_return = False # Track if function has return
        self.current_func_ret_ty = "" # Current function return type (initialize to empty string)

    def mangle(self, name):
        return name.replace('::', '_')


    def sizeof(self, ty):
        if ty.endswith('*'): return 8
        if ty == 'fnptr': return 8  # Function pointer type
        if ty.startswith('array<'): return 24  # ptr + len + cap
        # Strip const modifier if present
        if ty.startswith('const '):
            ty = ty[6:]
        # Handle signed/unsigned types
        if ty.startswith('unsigned ') or ty.startswith('signed '):
            ty = ty.split(' ', 1)[1]  # Strip the modifier for size calculation
        # Handle generic int<num>
        if ty.startswith('int<') and ty.endswith('>'):
            try:
                bits = int(ty[4:-1])
                return (bits + 7) // 8
            except:
                return 8
        if ty == 'char': return 1  # char is int<8>
        if ty == 'int<16>': return 2
        if ty == 'int<32>' or ty == 'float<32>': return 4
        if ty == 'int' or ty == 'float' or ty == 'float<64>' or ty == 'string': return 8
        if ty in self.structs: return self.structs[ty]['size']
        if ty in self.enums: return 4
        if ty in self.types:
            # Typedef (union type): size is max of all member types, aligned to max alignment
            max_size = 0
            for member_ty in self.types[ty]:
                # Strip const for size calculation
                mem_ty = member_ty[6:] if member_ty.startswith('const ') else member_ty
                mem_size = self.sizeof(mem_ty)
                if mem_size > max_size:
                    max_size = mem_size
            # Ensure at least 1 byte
            if max_size == 0:
                max_size = 1
            return max_size
        return 8

    # Helper methods for type properties
    def _is_integer_type(self, ty):
        """Check if a type is an integer type (int, char, or sized int)."""
        if not ty: return False
        if ty in ('int', 'char', 'int<8>', 'int<16>', 'int<32>', 'int<64>'):
            return True
        if ty.startswith('unsigned ') or ty.startswith('signed '):
            base = ty.split(' ', 1)[1]
            return base in ('int', 'char', 'int<8>', 'int<16>', 'int<32>', 'int<64>') or (base.startswith('int<') and base.endswith('>'))
        if ty.startswith('int<') and ty.endswith('>'):
            return True
        return False

    def _is_signed_type(self, ty):
        """Determine if an integer type is signed."""
        if not ty: return True
        if ty in ('int', 'char', 'int<8>', 'int<16>', 'int<32>', 'int<64>'):
            return True
        if ty.startswith('signed '):
            return True
        if ty.startswith('unsigned '):
            return False
        if ty.startswith('int<'):
            return True
        return True

    def _is_integer_like(self, ty):
        """Check if type is integer or pointer (both can be held in 64-bit register)."""
        if not ty: return False
        return self._is_integer_type(ty) or ty.endswith('*')

    def _is_aggregate(self, ty):
        """Check if a type is an aggregate type (struct or array)."""
        if not ty: return False
        if ty.endswith('*'): return False
        return ty in self.structs or ty.startswith('array<') or ty in self.types or (not ty.startswith('float') and self.sizeof(ty) > 8)

    def _returns_by_stack(self, ty):
        """Determine if a type is returned via a hidden pointer on the stack."""
        if not ty: return False
        if ty.endswith('*'): return False
        if ty in self.structs: return True
        if ty in self.types: return True
        if ty.startswith('array<'): return False # Arrays return in rax/rdx/rcx
        return not ty.startswith('float') and self.sizeof(ty) > 16

    def _is_float(self, ty):
        """Check if a type is a float type."""
        if not ty: return False
        return ty.startswith('float')

    def array_elem_type(self, ty):
        if ty.startswith('array<') and ty.endswith('>'):
            return ty[6:-1]
        return None

    def array_elem_size(self, ty):
        et = self.array_elem_type(ty)
        return self.sizeof(et) if et else 8

    def is_struct_type(self, ty):
        """Check if a type is a struct type."""
        return ty in self.structs

    def is_enum_type(self, ty):
        """Check if a type is an enum type."""
        return ty in self.enums

    def _get_expr_type(self, node):
        """Get the type of an expression node."""
        if not node:
            return 'void'
        tag = node[0]
        if tag == 'number':
            return 'int'
        if tag == 'float':
            return 'float'
        if tag == 'string':
            return 'string'
        if tag == 'char':
            return 'char'
        if tag == 'id':
            name = node[1]
            if name in self.local_vars:
                return self.local_vars[name][1]
            if name in self.global_vars:
                return self.global_vars[name]
            return 'int'
        if tag == 'binop':
            return self._get_expr_type(node[2])
        if tag == 'unary':
            op = node[1]
            sub_ty = self._get_expr_type(node[2])
            if op == '&':
                return sub_ty + '*'
            if op == '*':
                return sub_ty[:-1] if sub_ty.endswith('*') else 'void'
            return sub_ty
        if tag == 'member_access':
            base_ty = self._get_expr_type(node[1])
            if base_ty.endswith('*'):
                struct_ty = base_ty[:-1]
                if struct_ty in self.structs:
                    st = self.structs[struct_ty]
                    if node[2] in st['fields']:
                        return st['fields'][node[2]]['type']
            if base_ty in self.structs:
                st = self.structs[base_ty]
                if node[2] in st['fields']:
                    return st['fields'][node[2]]['type']
            return 'int'
        if tag == 'arrow_access':
            base_ty = self._get_expr_type(node[1])
            if base_ty.endswith('*'):
                struct_ty = base_ty[:-1]
                if struct_ty in self.structs:
                    st = self.structs[struct_ty]
                    if node[2] in st['fields']:
                        return st['fields'][node[2]]['type']
            return 'int'
        if tag == 'array_access':
            base_ty = self._get_expr_type(node[1])
            if base_ty.startswith('array<') and base_ty.endswith('>'):
                return base_ty[6:-1]
            # Handle [] on char* or string types - returns char
            if base_ty == 'char*' or base_ty == 'string':
                return 'char'
            # Handle [] on other pointer types - returns the pointed-to type
            if base_ty.endswith('*'):
                return base_ty[:-1]
            return 'int'
        if tag == 'call':
            target = node[1]
            if target[0] == 'member_access':
                method = target[2]
                base_ty = self._get_expr_type(target[1])
                if base_ty.startswith('array<') or base_ty == 'string' or base_ty == 'char*':
                    if method == 'length':
                        return 'int'
                    if method == 'replace' and base_ty == 'string':
                        return 'string'

                    if base_ty.startswith('array<') and method == 'pop':
                        return base_ty[6:-1]
                return 'void'
            name = target[1] if target[0] == 'id' else f"{target[1]}::{target[2]}"
            # Handle built-in c_str() function
            if name == 'c_str':
                return 'char*'
            if name in self.func_signatures:
                return self.func_signatures[name]
            return 'int'
        if tag == 'namespace_access':
            name = f"{node[1]}::{node[2]}"
            if name in self.func_signatures:
                return self.func_signatures[name]
            if name in self.global_vars:
                return self.global_vars[name]
            if node[1] in self.enums:
                return 'int'
            return 'int'
        if tag == 'init_list':
            # For init_list, we need context to determine the type
            # Return 'unknown' for now - caller should handle this
            return 'unknown'
        return 'int'

    def _get_case_value(self, expr):
        """Evaluate a case expression to an integer constant."""
        tag = expr[0]
        if tag == 'number':
            return expr[1]
        elif tag == 'char':
            return expr[1]  # char value is already an integer (ord)
        elif tag == 'namespace_access':
            base = expr[1]
            name = expr[2]
            # Look up in enums
            if base in self.enums and name in self.enums[base]:
                return self.enums[base][name]
            else:
                raise Exception(f"Unknown enum value {base}::{name}")
        else:
            # For other constant expressions, they should have been constant-folded
            raise Exception(f"Non-constant case expression: {tag}")

    def get_string_label(self, val):
        if val in self.string_literals:
            return self.string_literals[val]
        label = f".LC{self.str_count}"
        self.str_count += 1
        self.string_literals[val] = label
        
        safe_val = val.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r').replace('\0', '\\0')
        self.rodata.append(f"{label}:")
        self.rodata.append(f"    .string \"{safe_val}\"")
        return label

    def get_float_label(self, val):
        if val in self.float_literals:
            return self.float_literals[val]
        label = f".LCF{self.float_count}"
        self.float_count += 1
        self.float_literals[val] = label
        
        self.rodata.append(f"    .align 8")
        self.rodata.append(f"{label}:")
        self.rodata.append(f"    .double {val}")
        return label

    def get_lvalue(self, node):
        if node[0] == 'id':
            if node[1] in self.local_vars:
                var_info = self.local_vars[node[1]]
                offset = var_info[0]
                ty = var_info[1]
                return f"{offset}(%rbp)", ty
            if node[1] in self.global_vars:
                ty = self.global_vars[node[1]]
                return f"{node[1]}(%rip)", ty
            raise Exception(f"Unknown var {node[1]}")
        elif node[0] == 'namespace_access':
            name = f"{node[1]}::{node[2]}"
            if name in self.global_vars:
                ty = self.global_vars[name]
                return f"{self.mangle(name)}(%rip)", ty
            if name in self.func_signatures:
                return f"{self.mangle(name)}(%rip)", "fnptr"
            raise Exception(f"Unknown namespaced symbol {name}")
        elif node[0] == 'member_access':
            base_addr, base_ty = self.get_lvalue(node[1])
            if base_ty in self.structs:
                st = self.structs[base_ty]
                if node[2] in st['fields']:
                    finfo = st['fields'][node[2]]
                    if '(%rbp)' in base_addr:
                        off = int(base_addr.split('(')[0])
                        return f"{off + finfo['offset']}(%rbp)", finfo['type']
                    elif '(%r11)' in base_addr:
                        # Array element struct access: offset from r11
                        off = finfo['offset']
                        return f"{off}(%r11)", finfo['type']
                    elif '(%rax)' in base_addr:
                        # Pointer deref struct access: offset from rax
                        off = finfo['offset']
                        return f"{off}(%rax)", finfo['type']
            raise Exception(f"Unknown field {node[2]} on type {base_ty}")
        elif node[0] == 'arrow_access':
            # ptr->field: deref pointer, then offset to field
            ty = self.gen_expr(node[1])  # pointer in %rax
            if ty and ty.endswith('*'):
                struct_ty = ty[:-1]
                if struct_ty in self.structs:
                    st = self.structs[struct_ty]
                    if node[2] in st['fields']:
                        finfo = st['fields'][node[2]]
                        off = finfo['offset']
                        return f"{off}(%rax)", finfo['type']
            raise Exception(f"Unknown arrow field {node[2]} on type {ty}")
        elif node[0] == 'array_access':
            # arr[idx]: compute address of element
            base_addr, base_ty = self.get_lvalue(node[1])
            elem_ty = self.array_elem_type(base_ty)
            
            # Handle [] on char* or string types
            if base_ty == 'char*' or base_ty == 'string':
                elem_ty = 'char'
                elem_sz = 1
                # For string/char*, the variable IS the pointer (not a struct with data ptr)
                if '(%rbp)' in base_addr:
                    base_off = int(base_addr.split('(')[0])
                    self.text.append(f"    mov {base_off}(%rbp), %r11")  # pointer value
                elif '(%rip)' in base_addr:
                    self.text.append(f"    mov {base_addr}, %r11")
                else:
                    # It might be a string literal or expression result
                    self.text.append(f"    mov {base_addr}, %r11")
                # Evaluate index
                self.text.append("    push %r11")
                self.gen_expr(node[2])  # index in %rax
                self.text.append("    pop %r11")
                self.text.append(f"    add %rax, %r11")  # char is 1 byte, no scaling needed
                return "(%r11)", 'char'
            
            # Handle [] on other pointer types
            if base_ty.endswith('*') and not elem_ty:
                elem_ty = base_ty[:-1]  # Remove the *
                elem_sz = self.sizeof(elem_ty)
                # For pointers, the variable IS the pointer
                if '(%rbp)' in base_addr:
                    base_off = int(base_addr.split('(')[0])
                    self.text.append(f"    mov {base_off}(%rbp), %r11")  # pointer value
                elif '(%rip)' in base_addr:
                    self.text.append(f"    mov {base_addr}, %r11")
                else:
                    self.text.append(f"    mov {base_addr}, %r11")
                # Evaluate index
                self.text.append("    push %r11")
                self.gen_expr(node[2])  # index in %rax
                self.text.append("    pop %r11")
                self.text.append(f"    imul ${elem_sz}, %rax")
                self.text.append("    add %rax, %r11")
                return "(%r11)", elem_ty
            
            elem_sz = self.sizeof(elem_ty) if elem_ty else 8
            # Load data pointer
            if '(%rbp)' in base_addr:
                base_off = int(base_addr.split('(')[0])
                self.text.append(f"    mov {base_off}(%rbp), %r11")  # data ptr
            else:
                self.text.append(f"    mov {base_addr}, %r11")
            # Evaluate index
            self.text.append("    push %r11")
            self.gen_expr(node[2])  # index in %rax
            self.text.append("    pop %r11")
            self.text.append(f"    imul ${elem_sz}, %rax")
            self.text.append("    add %rax, %r11")
            return "(%r11)", elem_ty if elem_ty else 'int'
        elif node[0] == 'unary' and node[1] == '*':
            ty = self.gen_expr(node[2])
            return "(%rax)", ty[:-1] if ty.endswith('*') else 'void'
        raise Exception(f"Not an lvalue: {node[0]}")

    def generate(self, ast):
        self._current_ast = ast
        for node in ast:
            if node[0] == 'struct_decl':
                name, fields = node[1], node[2]
                offset = 0
                field_info = {}
                for fty, fname in fields:
                    sz = self.sizeof(fty)
                    align = sz if sz < 8 else 8
                    if offset % align != 0:
                        offset += align - (offset % align)
                    field_info[fname] = {'offset': offset, 'type': fty}
                    offset += sz
                if offset % 8 != 0:
                    offset += 8 - (offset % 8)
                self.structs[name] = {'size': offset, 'fields': field_info}
            elif node[0] == 'enum_decl':
                name, variants = node[1], node[2]
                val_map = {}
                for i, v in enumerate(variants):
                    val_map[v] = i
                self.enums[name] = val_map
            elif node[0] == 'type_decl':
                name, types = node[1], node[2]
                self.types[name] = types
            elif node[0] == 'extern':
                _, ty, name, params, varargs = node
                self.extern_funcs[name] = {'varargs': varargs}
                self.func_signatures[name] = ty
            elif node[0] == 'func':
                _, ty, name, params, body = node
                self.func_signatures[name] = ty
            elif node[0] == 'pub_var':
                _, ty, name, init = node
                self.global_vars[name] = ty
                sz = self.sizeof(ty)
                mangled = self.mangle(name)
                self.data.append(f".global {mangled}")
                self.data.append(f"{mangled}:")
                if init is None:
                    # Zero initialization for global variables without initializer
                    self.data.append(f"    .zero {sz}")
                elif init[0] == 'number':
                    if sz == 1: self.data.append(f"    .byte {init[1]}")
                    elif sz == 2: self.data.append(f"    .short {init[1]}")
                    elif sz == 4: self.data.append(f"    .long {init[1]}")
                    else: self.data.append(f"    .quad {init[1]}")
                elif init[0] == 'string':
                    label = self.get_string_label(init[1])
                    self.data.append(f"    .quad {label}")
                elif init[0] == 'float':
                    if sz == 4: self.data.append(f"    .float {init[1]}")
                    else: self.data.append(f"    .double {init[1]}")
                else:
                    self.data.append(f"    .zero {sz}")

        for node in ast:
            if node[0] == 'func':
                self.gen_func(node)

        out = []
        if self.rodata:
            out.append(".section .rodata")
            out.extend(self.rodata)
        if self.data:
            out.append(".section .data")
            out.extend(self.data)
        out.append(".text")
        out.extend(self.optimizer.optimize_asm(self.text) if self.optimizer else self.text)
        
        # Emit lambda functions
        for lambda_text in self.lambda_funcs:
            out.extend(self.optimizer.optimize_asm(lambda_text) if self.optimizer else lambda_text)
        
        if self.uses_str_add:
            out.append(self._get_str_add_asm())
        if self.uses_str_sub:
            out.append(self._get_str_sub_asm())
        if self.uses_str_replace:
            out.append(self._get_str_replace_asm())
            
        out.append('.section .note.GNU-stack,"",@progbits')
        return "\n".join(out) + "\n"
        
    def _get_str_add_asm(self):
        return """
.global __c5_str_add
.weak __c5_str_add
.type __c5_str_add, @function
__c5_str_add:
    push %rbp
    mov %rsp, %rbp
    push %r12
    push %r13
    push %r14
    mov %rdi, %r12
    mov %rsi, %r13
    call strlen@PLT
    mov %rax, %r14
    mov %r13, %rdi
    call strlen@PLT
    add %rax, %r14
    add $1, %r14
    mov %r14, %rdi
    call malloc@PLT
    mov %rax, %r14
    mov %r14, %rdi
    mov %r12, %rsi
    call strcpy@PLT
    mov %r14, %rdi
    mov %r13, %rsi
    call strcat@PLT
    mov %r14, %rax
    pop %r14
    pop %r13
    pop %r12
    leave
    ret
"""

    def _get_str_sub_asm(self):
        return """
.global __c5_str_sub
.weak __c5_str_sub
.type __c5_str_sub, @function
__c5_str_sub:
    push %rbp
    mov %rsp, %rbp
    push %r12
    push %r13
    push %r14
    push %r15
    mov %rdi, %r12
    mov %rsi, %r13
    call strdup@PLT
    mov %rax, %r14
    mov %r14, %rdi
    mov %r13, %rsi
    call strstr@PLT
    cmp $0, %rax
    je .Lend_sub
    mov %rax, %r15
    push %r15
    mov %r13, %rdi
    call strlen@PLT
    pop %r15
    add %rax, %r15
    mov %r15, %rdi
    call strlen@PLT
    add $1, %rax
    mov %rax, %rdx
    mov %r15, %rsi
    mov %r14, %rdi
    push %rsi
    push %rdx
    mov %r13, %rsi
    call strstr@PLT
    pop %rdx
    pop %rsi
    mov %rax, %rdi
    call memmove@PLT
.Lend_sub:
    mov %r14, %rax
    pop %r15
    pop %r14
    pop %r13
    pop %r12
    leave
    ret
"""

    def _get_str_replace_asm(self):
        return """
.global __c5_str_replace
.weak __c5_str_replace
.type __c5_str_replace, @function
__c5_str_replace:
    push %rbp
    mov %rsp, %rbp
    push %r15
    push %r14
    push %r13
    push %r12
    push %rbx
    sub $40, %rsp
    mov %rdi, %r12
    mov %rsi, %r13
    mov %rdx, %r14
    test %r12, %r12
    jz .Lreturn_null
    mov %r13, %rdi
    call strlen@PLT
    mov %rax, %r15
    test %rax, %rax
    jz .Lold_empty
    mov %r14, %rdi
    call strlen@PLT
    mov %rax, -8(%rbp)
    mov %r12, %rdi
    call strlen@PLT
    mov %rax, -16(%rbp)
    mov %r12, %rdi
    xor %rbx, %rbx
.Lcount_loop:
    mov %r13, %rsi
    call strstr@PLT
    test %rax, %rax
    je .Lcalc_size
    inc %rbx
    add %r15, %rax
    mov %rax, %rdi
    jmp .Lcount_loop
.Lcalc_size:
    mov -16(%rbp), %rax
    mov -8(%rbp), %rcx
    sub %r15, %rcx
    imul %rbx, %rcx
    add %rcx, %rax
    inc %rax
    mov %rax, %rdi
    call malloc@PLT
    test %rax, %rax
    je .Lreturn_null
    mov %rax, -24(%rbp)
    mov %rax, %rbx
.Lcopy_loop:
    mov %r12, %rdi
    mov %r13, %rsi
    call strstr@PLT
    test %rax, %rax
    je .Lcopy_rest
    mov %rax, %rdi
    sub %r12, %rdi
    mov %rdi, %rdx
    mov %r12, %rsi
    mov %rbx, %rdi
    mov %rax, -32(%rbp)
    call memcpy@PLT
    mov -32(%rbp), %rax
    sub %r12, %rax
    add %rax, %rbx
    mov -8(%rbp), %rdx
    mov %r14, %rsi
    mov %rbx, %rdi
    call memcpy@PLT
    add -8(%rbp), %rbx
    mov -32(%rbp), %r12
    add %r15, %r12
    jmp .Lcopy_loop
.Lcopy_rest:
    mov %r12, %rsi
    mov %rbx, %rdi
    call strcpy@PLT
    mov -24(%rbp), %rax
    jmp .Lepilogue
.Lold_empty:
    mov %r12, %rdi
    call strdup@PLT
    jmp .Lepilogue
.Lreturn_null:
    xor %rax, %rax
.Lepilogue:
    add $40, %rsp
    pop %rbx
    pop %r12
    pop %r13
    pop %r14
    pop %r15
    pop %rbp
    ret
"""
    def gen_func(self, node):
        _, ty, name, params, body = node
        self.local_vars = {}
        self.local_var_offset = 0
        self.current_func_ret_ty = ty  # Store return type for struct returns
        self.func_has_return = False  # Track if function has a return statement
        
        self.text.append(f".global {name}")
        self.text.append(f".type {name}, @function")
        self.text.append(f"{name}:")
        self.text.append("    push %rbp")
        self.text.append("    mov %rsp, %rbp")
        self.text.append("    sub $528, %rsp") # 512 (locals) + 8 (padding) + 8 (to keep 16 alignment with rbp/ra)
        
        int_regs = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
        float_regs = ["%xmm0", "%xmm1", "%xmm2", "%xmm3", "%xmm4", "%xmm5"]
        int_idx = 0
        float_idx = 0
        
        # For struct returns, the caller passes a hidden pointer as first arg
        if self._returns_by_stack(ty):
            self.local_var_offset -= 8
            self.local_vars['__ret_ptr'] = (self.local_var_offset, ty + '*')
            reg = int_regs[int_idx]
            int_idx += 1
            self.text.append(f"    mov {reg}, {self.local_var_offset}(%rbp)")
        
        for p in params:
            pty, pname = p
            if pty.startswith('array<'):
                # Array param: 3 int regs (ptr, len, cap) -> 24 bytes
                self.local_var_offset -= 24
                self.local_vars[pname] = (self.local_var_offset, pty)
                reg_ptr = int_regs[int_idx]; int_idx += 1
                reg_len = int_regs[int_idx]; int_idx += 1
                reg_cap = int_regs[int_idx]; int_idx += 1
                self.text.append(f"    mov {reg_ptr}, {self.local_var_offset}(%rbp)")      # data ptr
                self.text.append(f"    mov {reg_len}, {self.local_var_offset+8}(%rbp)")     # length
                self.text.append(f"    mov {reg_cap}, {self.local_var_offset+16}(%rbp)")    # capacity
            elif pty in self.structs:
                # Struct parameter: pass in registers if <= 16 bytes, otherwise by pointer
                st = self.structs[pty]
                st_sz = st['size']
                self.local_var_offset -= st_sz
                # Align to 8 bytes
                if abs(self.local_var_offset) % 8 != 0:
                    self.local_var_offset -= 8 - (abs(self.local_var_offset) % 8)
                self.local_vars[pname] = (self.local_var_offset, pty)
                
                if st_sz <= 16:
                    # Pass in up to 2 registers
                    # Copy first 8 bytes from first register
                    reg1 = int_regs[int_idx]
                    int_idx += 1
                    self.text.append(f"    mov {reg1}, {self.local_var_offset}(%rbp)")
                    if st_sz > 8:
                        # Copy second 8 bytes from second register
                        reg2 = int_regs[int_idx]
                        int_idx += 1
                        self.text.append(f"    mov {reg2}, {self.local_var_offset+8}(%rbp)")
                else:
                    # Passed by pointer - copy from pointer to local storage
                    reg_ptr = int_regs[int_idx]
                    int_idx += 1
                    self.text.append(f"    mov {reg_ptr}, %r11")  # Save pointer
                    # Copy struct data from pointer to local storage
                    for copy_off in range(0, st_sz, 8):
                        remaining = st_sz - copy_off
                        if remaining >= 8:
                            self.text.append(f"    mov {copy_off}(%r11), %rax")
                            self.text.append(f"    mov %rax, {self.local_var_offset+copy_off}(%rbp)")
                        elif remaining >= 4:
                            self.text.append(f"    movl {copy_off}(%r11), %eax")
                            self.text.append(f"    movl %eax, {self.local_var_offset+copy_off}(%rbp)")
                        elif remaining >= 2:
                            self.text.append(f"    movw {copy_off}(%r11), %ax")
                            self.text.append(f"    movw %ax, {self.local_var_offset+copy_off}(%rbp)")
                        else:
                            self.text.append(f"    movb {copy_off}(%r11), %al")
                            self.text.append(f"    movb %al, {self.local_var_offset+copy_off}(%rbp)")
            elif pty.startswith('float'):
                self.local_var_offset -= 8
                self.local_vars[pname] = (self.local_var_offset, pty)
                reg = float_regs[float_idx]
                float_idx += 1
                if pty == 'float<32>':
                    self.text.append(f"    movss {reg}, {self.local_var_offset}(%rbp)")
                else:
                    self.text.append(f"    movsd {reg}, {self.local_var_offset}(%rbp)")
            else:
                self.local_var_offset -= 8
                self.local_vars[pname] = (self.local_var_offset, pty)
                reg = int_regs[int_idx]
                int_idx += 1
                self.text.append(f"    mov {reg}, {self.local_var_offset}(%rbp)")
            
        for stmt in body:
            self.gen_stmt(stmt)
            
        # Only add default return if no return statement was generated
        if not self.func_has_return:
            if name == "main":
                self.text.append("    mov $0, %eax")

            self.text.append("    leave")
            self.text.append("    ret")

    def gen_stmt(self, node):
        if node[0] == 'expr_stmt':
            ret_ty = self.gen_expr(node[1])
            if ret_ty in self.structs:
                st_sz = self.sizeof(ret_ty)
                if st_sz % 16 != 0: st_sz += 16 - (st_sz % 16)
                self.text.append(f"    add ${st_sz}, %rsp")
        elif node[0] == 'var_decl':
            _, ty, name, init_expr = node
            # Check if init expression is a lambda - use 8 bytes for function pointer
            if init_expr and init_expr[0] == 'lambda':
                sz = 8  # Function pointer size
            else:
                sz = self.sizeof(ty)
            align = sz if sz < 8 else 8
            align = 8 if align == 8 else align
            if abs(self.local_var_offset) % align != 0:
                self.local_var_offset -= align - (abs(self.local_var_offset) % align)
            self.local_var_offset -= sz
            self.local_vars[name] = (self.local_var_offset, ty)
            
            # For lambdas, store the expected return type for proper code generation
            if init_expr and init_expr[0] == 'lambda':
                self.local_vars[name] = (self.local_var_offset, ty, True)  # Mark as lambda var
            
            # Zero-initialize aggregates when declared without initializer
            if not init_expr and self._is_aggregate(ty):
                base_off = self.local_var_offset
                sz = self.sizeof(ty)
                if sz <= 24: # Small size, use inline movs
                    for i in range(0, sz, 8):
                        if i + 8 <= sz:
                            self.text.append(f"    movq $0, {base_off+i}(%rbp)")
                        elif sz - i == 4:
                            self.text.append(f"    movl $0, {base_off+i}(%rbp)")
                        elif sz - i == 2:
                            self.text.append(f"    movw $0, {base_off+i}(%rbp)")
                        elif sz - i == 1:
                            self.text.append(f"    movb $0, {base_off+i}(%rbp)")
                else:
                    self.text.append(f"    lea {base_off}(%rbp), %rdi")
                    self.text.append("    xor %rsi, %rsi")
                    self.text.append(f"    mov ${sz}, %rdx")
                    self.text.append("    call memset@PLT")
            
            if init_expr:
                # Set expected return type for lambda expressions
                if init_expr[0] == 'lambda':
                    self.lambda_ret_type = ty
                
                if init_expr[0] == 'init_list':
                    # Recursive initialization
                    self._gen_init_list_recursive(init_expr, ty)
                    # Result is on stack (aggregate or primitive), copy to local variable
                    sz = self.sizeof(ty)
                    self.text.append(f"    lea {self.local_var_offset}(%rbp), %rdi")
                    self.text.append("    mov %rsp, %rsi")
                    self.text.append(f"    mov ${sz}, %rdx")
                    self.text.append("    call memcpy@PLT")
                    self.text.append(f"    add ${sz}, %rsp") # pop temp
                else:
                    ret_ty = self.gen_expr(init_expr)
                    if ret_ty:
                        self.text.append(f"    # DEBUG: ret_ty={ret_ty}")
                    if ret_ty == 'fnptr':
                        # Lambda expression - always store as 8-byte pointer
                        self.text.append(f"    mov %rax, {self.local_var_offset}(%rbp)")
                        # Clean up lambda return type
                        if hasattr(self, 'lambda_ret_type'):
                            delattr(self, 'lambda_ret_type')
                    elif self._returns_by_stack(ret_ty) or (ret_ty and ret_ty.endswith('*') and not ty.endswith('*') and self._is_aggregate(ret_ty[:-1])):
                        # Function returns a struct by value (rax=rsp) or pointer (rax=ptr)
                        is_on_stack = self._returns_by_stack(ret_ty)
                        src_ty = ret_ty if is_on_stack else ret_ty[:-1]
                        st_sz = self.sizeof(src_ty)
                        self.text.append("    mov %rax, %rsi")  # src
                        self.text.append(f"    lea {self.local_var_offset}(%rbp), %rdi")  # dest
                        self.text.append(f"    mov ${st_sz}, %rdx")
                        self.text.append("    call memcpy@PLT")
                        if is_on_stack:
                            # Clean up stack temporary
                            pad_sz = st_sz
                            if pad_sz % 16 != 0: pad_sz += 16 - (pad_sz % 16)
                            self.text.append(f"    add ${pad_sz}, %rsp")
                    elif self._is_float(ty):
                        if ty == 'float<32>':
                            if ret_ty == 'float' or ret_ty == 'float<64>':
                                self.text.append("    cvtsd2ss %xmm0, %xmm0")
                            self.text.append(f"    movss %xmm0, {self.local_var_offset}(%rbp)")
                        else:
                            if ret_ty == 'float<32>':
                                self.text.append("    cvtss2sd %xmm0, %xmm0")
                            self.text.append(f"    movsd %xmm0, {self.local_var_offset}(%rbp)")
                    elif ty.startswith('array<'):
                        # Assign from function return: copy 24 bytes
                        base_off = self.local_var_offset
                        self.text.append(f"    mov %rax, {base_off}(%rbp)")       # data ptr
                        self.text.append(f"    mov %rdx, {base_off+8}(%rbp)")     # length
                        self.text.append(f"    mov %rcx, {base_off+16}(%rbp)")    # capacity
                    else:
                        sz = self.sizeof(ty)
                        if sz == 1: self.text.append(f"    mov %al, {self.local_var_offset}(%rbp)")
                        elif sz == 2: self.text.append(f"    mov %ax, {self.local_var_offset}(%rbp)")
                        elif sz == 4: self.text.append(f"    mov %eax, {self.local_var_offset}(%rbp)")
                        else: self.text.append(f"    mov %rax, {self.local_var_offset}(%rbp)")
        elif node[0] == 'try_catch_stmt':
            self.gen_try_catch(node)
        elif node[0] == 'return_stmt':
            self.func_has_return = True
            if node[1]:
                ret_expr = node[1]
                # Check if we're returning an array variable
                if ret_expr[0] == 'id' and ret_expr[1] in self.local_vars:
                    var_info = self.local_vars[ret_expr[1]]
                    off = var_info[0]
                    vty = var_info[1]
                    if vty.startswith('array<'):
                        self.text.append(f"    mov {off}(%rbp), %rax")       # data ptr
                        self.text.append(f"    mov {off+8}(%rbp), %rdx")     # length
                        self.text.append(f"    mov {off+16}(%rbp), %rcx")    # capacity
                        self.text.append("    leave")
                        self.text.append("    ret")
                        return
                
                # Check if returning a struct - use function's return type
                func_ret_ty = getattr(self, 'current_func_ret_ty', 'int')
                if self._returns_by_stack(func_ret_ty):
                    # Get the hidden return pointer
                    ret_ptr_off = self.local_vars['__ret_ptr'][0]
                    self.text.append(f"    mov {ret_ptr_off}(%rbp), %r11")  # dest ptr in r11
                    
                    if ret_expr[0] == 'init_list':
                        # Initialize struct fields directly at the return pointer
                        st = self.structs[func_ret_ty]
                        field_list = list(st['fields'].items())
                        for i, fval in enumerate(ret_expr[1]):
                            fname, finfo = field_list[i]
                            self.gen_expr(fval)
                            foff = finfo['offset']
                            if finfo['type'].startswith('float'):
                                if finfo['type'] == 'float<32>':
                                    self.text.append(f"    movss %xmm0, {foff}(%r11)")
                                else:
                                    self.text.append(f"    movsd %xmm0, {foff}(%r11)")
                            else:
                                fsz = self.sizeof(finfo['type'])
                                if fsz == 1:
                                    self.text.append(f"    mov %al, {foff}(%r11)")
                                elif fsz == 2:
                                    self.text.append(f"    mov %ax, {foff}(%r11)")
                                elif fsz == 4:
                                    self.text.append(f"    mov %eax, {foff}(%r11)")
                                else:
                                    self.text.append(f"    mov %rax, {foff}(%r11)")
                    elif ret_expr[0] == 'id' and ret_expr[1] in self.local_vars:
                        # Copy struct variable to return location
                        src_off = self.local_vars[ret_expr[1]][0]
                        st_sz = self.sizeof(func_ret_ty)
                        # Use memcpy for the copy
                        self.text.append(f"    lea {src_off}(%rbp), %rsi")  # src
                        self.text.append("    mov %r11, %rdi")  # dest
                        self.text.append(f"    mov ${st_sz}, %rdx")
                        self.text.append("    call memcpy@PLT")
                    else:
                        # General expression - evaluate and copy
                        # The expression should return a pointer to the struct
                        self.gen_expr(ret_expr)
                        # rax now contains pointer to source struct
                        st_sz = self.sizeof(func_ret_ty)
                        self.text.append("    mov %r11, %rdi")  # dest
                        self.text.append("    mov %rax, %rsi")  # src
                        self.text.append(f"    mov ${st_sz}, %rdx")
                        self.text.append("    call memcpy@PLT")
                    
                    self.text.append("    leave")
                    self.text.append("    ret")
                    return
                
                ty_e = self.gen_expr(ret_expr)
                if ty_e and ty_e.startswith('array<'):
                    # Load array fields into rax, rdx, rcx for return
                    self.text.append("    mov (%rax), %r11")
                    self.text.append("    mov 8(%rax), %rdx")
                    self.text.append("    mov 16(%rax), %rcx")
                    self.text.append("    mov %r11, %rax")
            self.text.append("    leave")
            self.text.append("    ret")
        elif node[0] == 'while_stmt':
            cond, body = node[1], node[2]
            self.label_count += 1
            cond_label = f".Lwhile_cond_{self.label_count}"
            end_label = f".Lwhile_end_{self.label_count}"
            
            self.text.append(f"{cond_label}:")
            self.gen_expr(cond)
            self.text.append("    cmp $0, %rax")
            self.text.append(f"    je {end_label}")
            self.break_targets.append(end_label)
            for stmt in body:
                self.gen_stmt(stmt)
            self.break_targets.pop()
            self.text.append(f"    jmp {cond_label}")
            self.text.append(f"{end_label}:")
        elif node[0] == 'do_while_stmt':
            body, cond = node[1], node[2]
            self.label_count += 1
            start_label = f".Ldo_start_{self.label_count}"
            end_label = f".Ldo_end_{self.label_count}"
            self.text.append(f"{start_label}:")
            self.break_targets.append(end_label)
            for stmt in body:
                self.gen_stmt(stmt)
            self.break_targets.pop()
            self.gen_expr(cond)
            self.text.append("    cmp $0, %rax")
            self.text.append(f"    jne {start_label}")
            self.text.append(f"{end_label}:")
        elif node[0] == 'for_stmt':
            init, cond, inc, body = node[1], node[2], node[3], node[4]
            self.label_count += 1
            cond_label = f".Lfor_cond_{self.label_count}"
            end_label = f".Lfor_end_{self.label_count}"
            
            self.gen_stmt(init)
            self.text.append(f"{cond_label}:")
            self.gen_expr(cond)
            self.text.append("    cmp $0, %rax")
            self.text.append(f"    je {end_label}")
            self.break_targets.append(end_label)
            for stmt in body:
                self.gen_stmt(stmt)
            self.break_targets.pop()
            self.gen_expr(inc)
            self.text.append(f"    jmp {cond_label}")
            self.text.append(f"{end_label}:")
        elif node[0] == 'foreach_stmt':
            # foreach (index_var, value_var in array_expr) { body }
            index_var, value_var, array_expr, body = node[1], node[2], node[3], node[4]
            
            self.label_count += 1
            cond_label = f".Lforeach_cond_{self.label_count}"
            end_label = f".Lforeach_end_{self.label_count}"
            
            # Get array type and element size
            array_ty = self._get_expr_type(array_expr)
            elem_ty = 'int'
            if array_ty.startswith('array<') and array_ty.endswith('>'):
                elem_ty = array_ty[6:-1]
            elif array_ty == 'string' or array_ty == 'char*':
                elem_ty = 'char'
            elem_sz = self.sizeof(elem_ty)
            
            # Check if element type is a struct
            is_struct = elem_ty in self.structs or elem_ty.startswith('array<') or elem_ty in self.types or self.sizeof(elem_ty) > 8
            
            # Check if array_expr is a simple variable reference
            is_global_array = False
            is_string_type = array_ty == 'string' or array_ty == 'char*'
            
            if not is_string_type:
                if array_expr[0] == 'id' and array_expr[1] in self.local_vars:
                    # Use the existing local array variable directly
                    array_off = self.local_vars[array_expr[1]][0]
                elif array_expr[0] == 'id' and array_expr[1] in self.global_vars:
                    # Global array - load address into r12
                    is_global_array = True
                    array_name = array_expr[1]
                    self.text.append(f"    lea {array_name}(%rip), %r12")
                    array_off = None  # Not used for global arrays
                else:
                    # Allocate the array variable if it's an expression
                    # Store array in a local variable (ptr, len, cap)
                    self.local_var_offset -= 24
                    array_off = self.local_var_offset
                    
                    # Evaluate array expression and store it
                    self.gen_expr(array_expr)
                    # Expression returned pointer to header in %rax
                    self.text.append("    mov (%rax), %r11")
                    self.text.append(f"    mov %r11, {array_off}(%rbp)")       # data ptr
                    self.text.append("    mov 8(%rax), %r11")
                    self.text.append(f"    mov %r11, {array_off+8}(%rbp)")     # length
                    self.text.append("    mov 16(%rax), %r11")
                    self.text.append(f"    mov %r11, {array_off+16}(%rbp)")    # capacity
            else:
                # For strings, normalize to a temp (ptr, len)
                self.local_var_offset -= 16
                array_off = self.local_var_offset
                self.gen_expr(array_expr)
                self.text.append(f"    mov %rax, {array_off}(%rbp)")
                self.text.append("    mov %rax, %rdi")
                self.text.append("    call strlen@PLT")
                self.text.append(f"    mov %rax, {array_off+8}(%rbp)")
            
            # Helper to access array fields
            def arr_field(off):
                if is_global_array:
                    return f"{off}(%r12)"
                else:
                    return f"{array_off+off}(%rbp)"
            
            # Allocate index variable (init to 0)
            self.local_var_offset -= 8
            index_off = self.local_var_offset
            self.local_vars[index_var] = (index_off, 'int')
            self.text.append(f"    movq $0, {index_off}(%rbp)")
            
            # Allocate value variable - use actual element size
            # For structs or large types, align then allocate full size
            if is_struct or elem_sz > 8:
                # Align to 8 bytes
                if abs(self.local_var_offset) % 8 != 0:
                    self.local_var_offset -= 8 - (abs(self.local_var_offset) % 8)
            self.local_var_offset -= elem_sz
            value_off = self.local_var_offset
            self.local_vars[value_var] = (value_off, elem_ty)
            
            # Loop: while (index < array.length)
            self.text.append(f"{cond_label}:")
            # Load index
            self.text.append(f"    mov {index_off}(%rbp), %rax")
            # Load array length
            self.text.append(f"    mov {arr_field(8)}, %rcx")
            # Compare index < length
            self.text.append("    cmp %rcx, %rax")
            self.text.append(f"    jge {end_label}")
            
            # Load value = array[index]
            # Load data pointer
            self.text.append(f"    mov {arr_field(0)}, %r11")
            # Calculate offset: index * elem_sz
            self.text.append(f"    mov {index_off}(%rbp), %rax")
            self.text.append(f"    imul ${elem_sz}, %rax")
            self.text.append("    add %rax, %r11")
            
            # Load element at r11 into value variable
            if is_struct or elem_sz > 8:
                # Use memcpy for struct types or large elements
                self.text.append(f"    lea {value_off}(%rbp), %rdi")  # dest
                self.text.append("    mov %r11, %rsi")  # src
                self.text.append(f"    mov ${elem_sz}, %rdx")  # size
                self.text.append("    call memcpy@PLT")
            elif elem_sz == 1:
                self.text.append(f"    movzbq (%r11), %rax")
                self.text.append(f"    mov %al, {value_off}(%rbp)")
            elif elem_sz == 2:
                self.text.append(f"    movzwq (%r11), %rax")
                self.text.append(f"    mov %ax, {value_off}(%rbp)")
            elif elem_sz == 4:
                self.text.append(f"    movl (%r11), %eax")
                self.text.append(f"    mov %eax, {value_off}(%rbp)")
            else:
                # elem_sz == 8
                self.text.append(f"    movq (%r11), %rax")
                self.text.append(f"    mov %rax, {value_off}(%rbp)")
            
            # Execute body
            self.break_targets.append(end_label)
            for stmt in body:
                self.gen_stmt(stmt)
            self.break_targets.pop()
            
            # Increment index
            self.text.append(f"    incq {index_off}(%rbp)")
            self.text.append(f"    jmp {cond_label}")
            self.text.append(f"{end_label}:")
        elif node[0] == 'break_stmt':
            if not self.break_targets:
                raise Exception("break statement not inside a loop or switch")
            target = self.break_targets[-1]
            self.text.append(f"    jmp {target}")
        elif node[0] == 'switch_stmt':
            # Node structure: ('switch_stmt', cond, cases, default_body) after stripping loc
            cond, cases, default_body = node[1], node[2], node[3]
            self.label_count += 1
            end_label = f".Lswitch_end_{self.label_count}"
            
            # Evaluate switch condition into %rax
            self.gen_expr(cond)
            
            # Generate case labels
            case_labels = []
            for i, case in enumerate(cases):
                case_label = f".Lcase_{self.label_count}_{i}"
                case_labels.append(case_label)
            
            # For each case, generate comparison
            for i, case in enumerate(cases):
                case_val = self._get_case_value(case[1])
                self.text.append(f"    cmp ${case_val}, %rax")
                self.text.append(f"    je {case_labels[i]}")
            
            # If no case matched, jump to default or end
            if default_body:
                default_label = f".Ldefault_{self.label_count}"
                self.text.append(f"    jmp {default_label}")
            else:
                self.text.append(f"    jmp {end_label}")
            
            # Push break target for switch body
            self.break_targets.append(end_label)
            
            # Emit case bodies
            for i, case in enumerate(cases):
                self.text.append(f"{case_labels[i]}:")
                case_body = case[2]
                for stmt in case_body:
                    self.gen_stmt(stmt)
                # No explicit jump after case; fall-through allowed
            
            # Emit default body if present
            if default_body:
                self.text.append(f"{default_label}:")
                for stmt in default_body:
                    self.gen_stmt(stmt)
            
            self.break_targets.pop()
            self.text.append(f"{end_label}:")
        elif node[0] == 'if_stmt':
            cond, body, else_body = node[1], node[2], node[3]
            self.label_count += 1
            else_label = f".Lelse_{self.label_count}"
            end_label = f".Lend_{self.label_count}"
            
            self.gen_expr(cond)
            self.text.append("    cmp $0, %rax")
            if else_body is not None:
                self.text.append(f"    je {else_label}")
            else:
                self.text.append(f"    je {end_label}")
                
            for stmt in body:
                self.gen_stmt(stmt)
                
            if else_body is not None:
                self.text.append(f"    jmp {end_label}")
                self.text.append(f"{else_label}:")
                for stmt in else_body:
                    self.gen_stmt(stmt)
                    
            self.text.append(f"{end_label}:")

    def gen_try_catch(self, node):
        # node structure: ('try_catch_stmt', try_body, catch_param, catch_body, loc)
        try_body = node[1]
        catch_param = node[2]
        catch_body = node[3]
        loc = node[4]
        
        # Retrieve errors collected for this try-catch block
        errors_list = self.try_errors_map.get(loc, [])
        # Group errors by statement index
        errors_by_index = {}
        for err in errors_list:
            idx = err['index']
            if idx not in errors_by_index:
                errors_by_index[idx] = []
            errors_by_index[idx].append(err)
        
        # Generate labels
        self.label_count += 1
        catch_label = f".Lcatch_{self.label_count}"
        end_label = f".Ltry_end_{self.label_count}"
        
        # Generate try body with pre-checks
        error_handlers = []  # List of (handler_label, message_label) pairs
        err_counter = 0
        for i, stmt in enumerate(try_body):
            # Pre-check for errors associated with this statement
            if i in errors_by_index:
                for err in errors_by_index[i]:
                    code = err['code']
                    msg = err.get('msg', '')
                    stmt_node = err.get('stmt_node')
                    # Currently handle only E023 (integer overflow)
                    if code == 'E023' and stmt_node:
                        # Extract value and type from the statement
                        value = None
                        ty = None
                        if stmt_node[0] == 'var_decl':
                            ty = stmt_node[1]
                            init = stmt_node[3]
                            if init and init[0] == 'number':
                                value = init[1]
                        elif stmt_node[0] == 'assign':
                            right = stmt_node[2]
                            if right[0] == 'number':
                                value = right[1]
                                # Try to get target type from left-hand side
                                left = stmt_node[1]
                                ty = self._get_expr_type(left)
                        if value is not None and ty is not None:
                            min_val, max_val = self._int_type_range(ty)
                            if min_val is not None and max_val is not None:
                                # Determine signedness
                                signed = not ty.startswith('unsigned ')
                                # Create an error handler label for this specific error
                                handler_label = f".Lerr_{self.label_count}_{err_counter}"
                                err_counter += 1
                                # Get or create string label for the error message
                                err_msg = msg if msg else f"Integer overflow: value {value} does not fit in type {ty}"
                                msg_label = self.get_string_label(err_msg)
                                error_handlers.append((handler_label, msg_label))
                                # Load constant into %rax
                                self.text.append(f"    mov ${value}, %rax")
                                # Compare with min
                                if signed:
                                    self.text.append(f"    cmp ${min_val}, %rax")
                                    self.text.append(f"    jl {handler_label}")
                                else:
                                    # Unsigned: min is 0, so only check > max
                                    pass
                                # Compare with max
                                if signed:
                                    self.text.append(f"    cmp ${max_val}, %rax")
                                    self.text.append(f"    jg {handler_label}")
                                else:
                                    self.text.append(f"    cmp ${max_val}, %rax")
                                    self.text.append(f"    ja {handler_label}")
                                continue  # generated check, skip to next error or statement
                        # If we couldn't generate a check, fall through to treat as generic error
                    # For other error types or if extraction failed, treat as generic error with message
                    # Generate a generic check that always triggers (since error condition is static)
                    # But we need a condition. For now, we'll just generate an unconditional jump if we have a msg?
                    # Actually, we can't just always jump; the error might be conditional. For simplicity, we'll generate a check that always fails if we can't do better.
                    # We'll generate: mov $1, %rax; test %rax, %rax; jmp catch_label (always)
                    # But that would always jump, which is okay if the error is definite.
                    # However, we don't know if the error is definite. For now, skip generic handling.
                    # Generic error handling: generate an unconditional jump to catch with error message
                    handler_label = f".Lerr_{self.label_count}_{err_counter}"
                    err_counter += 1
                    err_msg = msg if msg else f"Error: {code}"
                    msg_label = self.get_string_label(err_msg)
                    error_handlers.append((handler_label, msg_label))
                    self.text.append(f"    jmp {handler_label}")
            # Generate the statement normally
            self.gen_stmt(stmt)
        
        # After successful try block, skip catch
        self.text.append(f"    jmp {end_label}")
        
        # Emit error handler blocks: set %rdi with error message and jump to catch
        for handler_label, msg_label in error_handlers:
            self.text.append(f"{handler_label}:")
            self.text.append(f"    lea {msg_label}(%rip), %rdi")
            self.text.append(f"    jmp {catch_label}")
        
        # Generate catch block
        self.text.append(f"{catch_label}:")
        # Allocate space for catch parameter (string) on the stack
        internal_name = f"__catch_{catch_param}_{self.catch_param_counter}"
        self.catch_param_counter += 1
        sz = 8  # string is 8 bytes (pointer)
        if abs(self.local_var_offset) % 8 != 0:
            self.local_var_offset -= 8 - (abs(self.local_var_offset) % 8)
        self.local_var_offset -= sz
        self.local_vars[internal_name] = (self.local_var_offset, 'string')
        # Store the error string pointer (passed in %rdi) into this slot
        self.text.append(f"    mov %rdi, {self.local_var_offset}(%rbp)")
        # Rewrite catch_body to replace references to catch_param with internal_name
        mapping = {catch_param: internal_name}
        rewritten_catch_body = self.rewrite_ids(catch_body, mapping)
        # Generate catch body
        for s in rewritten_catch_body:
            self.gen_stmt(s)
        
        # End label
        self.text.append(f"{end_label}:")
    
    def rewrite_ids(self, node, mapping):
        """Recursively rewrite id nodes according to mapping."""
        if isinstance(node, tuple):
            tag = node[0]
            # If it's an id and in mapping, replace
            if tag == 'id' and node[1] in mapping:
                # Keep location (last element)
                return ('id', mapping[node[1]], node[-1])
            # Otherwise, recurse on children
            new_children = []
            for child in node[1:]:
                if isinstance(child, (tuple, list)):
                    new_children.append(self.rewrite_ids(child, mapping))
                else:
                    new_children.append(child)
            return (node[0],) + tuple(new_children)
        elif isinstance(node, list):
            return [self.rewrite_ids(item, mapping) for item in node]
        else:
            return node
    
    def _int_type_range(self, ty):
        """Return (min_val, max_val) for integer type, or (None, None) if not applicable."""
        # Strip const and signed/unsigned modifiers
        base_ty = ty
        # Remove const
        if base_ty.startswith('const '):
            base_ty = base_ty[6:]
        signed = True
        if base_ty.startswith('unsigned '):
            signed = False
            base_ty = base_ty[9:]
        elif base_ty.startswith('signed '):
            signed = True
            base_ty = base_ty[7:]
        # Determine bit width
        if base_ty == 'int':
            bits = 64
        elif base_ty == 'char':
            bits = 8
        elif base_ty.startswith('int<') and base_ty.endswith('>'):
            try:
                bits = int(base_ty[4:-1])
            except:
                return (None, None)
        else:
            return (None, None)
        if signed:
            min_val = -(1 << (bits - 1))
            max_val = (1 << (bits - 1)) - 1
        else:
            min_val = 0
            max_val = (1 << bits) - 1
        return (min_val, max_val)
    def _gen_init_list_recursive(self, node, target_ty):
        """
        Generates code for an initializer list (node) of type target_ty.
        Leaves the resulting value/struct on the stack.
        Returns the type (target_ty).
        """
        if node[0] != 'init_list':
            res_ty = self.gen_expr(node)
            if self._is_float(res_ty) and self._is_float(target_ty) and res_ty != target_ty:
                if target_ty == 'float<32>': self.text.append("    cvtsd2ss %xmm0, %xmm0")
                else: self.text.append("    cvtss2sd %xmm0, %xmm0")
            
            if self._is_float(target_ty):
                self.text.append("    sub $8, %rsp")
                if target_ty == 'float<32>': self.text.append("    movss %xmm0, (%rsp)")
                else: self.text.append("    movsd %xmm0, (%rsp)")
            elif self._is_aggregate(target_ty):
                # Copy existing aggregate to stack
                sz = self.sizeof(target_ty)
                self.text.append(f"    sub ${sz}, %rsp")
                self.text.append("    mov %rax, %rsi") # src (addr returned by gen_expr for aggregates)
                self.text.append("    mov %rsp, %rdi") # dest
                self.text.append(f"    mov ${sz}, %rdx")
                self.text.append("    sub $8, %rsp") # Ensure alignment
                self.text.append("    call memcpy@PLT")
                self.text.append("    add $8, %rsp")
            else:
                self.text.append("    push %rax")
            return target_ty

        if target_ty and target_ty.startswith('array<'):
            elem_ty = self.array_elem_type(target_ty)
            elem_sz = self.sizeof(elem_ty)
            items = node[1]
            count = len(items)
            alloc_sz = count * elem_sz if count > 0 else 8
            
            self.text.append("    sub $8, %rsp") # ALIGN (assuming entry at 16k or 16k+8)
            self.text.append(f"    mov ${alloc_sz}, %rdi")
            self.text.append("    call malloc@PLT")
            self.text.append("    add $8, %rsp") # RESTORE
            self.text.append("    push %rax") # data_ptr at (%rsp)
            
            for i, item in enumerate(items):
                self._gen_init_list_recursive(item, elem_ty)
                p_sz = self.sizeof(elem_ty) if self._is_aggregate(elem_ty) else 8
                self.text.append(f"    mov {p_sz}(%rsp), %rdi") # data_ptr
                self.text.append(f"    add ${i * elem_sz}, %rdi") # dest
                self.text.append("    mov %rsp, %rsi") # src
                self.text.append(f"    mov ${elem_sz}, %rdx")
                self.text.append("    call memcpy@PLT")
                self.text.append(f"    add ${p_sz}, %rsp")
            
            self.text.append(f"    movq ${count}, %rax")
            self.text.append("    push %rax") # cap
            self.text.append("    push %rax") # len
            # Initial order: [ptr, cap, len] (wrong)
            # Wait, no. Current stack: [len, cap, ptr]
            # pop rdx (len), pop rcx (cap), pop rax (ptr)
            # push rcx (cap), push rdx (len), push rax (ptr)
            # Top of stack: [ptr, len, cap] (correct for 24-byte array struct)
            self.text.append("    pop %rdx") # len
            self.text.append("    pop %rcx") # cap
            self.text.append("    pop %rax") # ptr
            self.text.append("    push %rcx") # cap
            self.text.append("    push %rdx") # len
            self.text.append("    push %rax") # ptr
            return target_ty

        if target_ty in self.structs:
            st = self.structs[target_ty]
            st_sz = st['size']
            fields = list(st['fields'].items())
            items = node[1]
            
            self.text.append(f"    sub ${st_sz}, %rsp")
            for i, item in enumerate(items):
                if i >= len(fields): break
                fname, finfo = fields[i]
                f_ty = finfo['type']
                self._gen_init_list_recursive(item, f_ty)
                p_sz = self.sizeof(f_ty) if self._is_aggregate(f_ty) else 8
                self.text.append(f"    lea {p_sz + finfo['offset']}(%rsp), %rdi") # dest
                self.text.append("    mov %rsp, %rsi") # src
                self.text.append(f"    mov ${self.sizeof(f_ty)}, %rdx")
                self.text.append("    call memcpy@PLT")
                self.text.append(f"    add ${p_sz}, %rsp")
            return target_ty
            
        return target_ty

    def gen_expr(self, node):
        if node[0] == 'number':
            self.text.append(f"    mov ${node[1]}, %rax")
            return "int"
        elif node[0] == 'float':
            label = self.get_float_label(node[1])
            self.text.append(f"    movsd {label}(%rip), %xmm0")
            return "float"
        elif node[0] == 'char':
            self.text.append(f"    mov ${node[1]}, %rax")
            return "char"
        elif node[0] == 'string':
            label = self.get_string_label(node[1])
            self.text.append(f"    lea {label}(%rip), %rax")
            return "string"
        elif node[0] == 'namespace_access' and node[1] in self.enums:
            base, name = node[1], node[2]
            val = self.enums[base][name]
            self.text.append(f"    mov ${val}, %rax")
            return "int"
        elif node[0] == 'lambda':
            # Lambda expression: generate a unique function and return its address
            params, body = node[1], node[2]
            self.lambda_count += 1
            lambda_name = f"__lambda_{self.lambda_count}"
            
            # Get expected return type from context (passed via lambda_ret_type attribute)
            lambda_ret_ty = getattr(self, 'lambda_ret_type', 'int')
            
            # Store current state
            saved_local_vars = self.local_vars.copy()
            saved_local_var_offset = self.local_var_offset
            saved_text = self.text
            saved_func_ret_ty = getattr(self, 'current_func_ret_ty', 'int')
            saved_func_has_return = getattr(self, 'func_has_return', False)
            
            # Generate lambda function
            self.local_vars = {}
            self.local_var_offset = 0
            self.func_has_return = False
            lambda_text = []
            
            self.current_func_ret_ty = lambda_ret_ty
            
            lambda_text.append(f".global {lambda_name}")
            lambda_text.append(f".type {lambda_name}, @function")
            lambda_text.append(f"{lambda_name}:")
            lambda_text.append("    push %rbp")
            lambda_text.append("    mov %rsp, %rbp")
            lambda_text.append("    sub $528, %rsp") # align 512 locals with ra/rbp
            
            int_regs = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
            float_regs = ["%xmm0", "%xmm1", "%xmm2", "%xmm3", "%xmm4", "%xmm5"]
            int_idx = 0
            float_idx = 0
            
            # For struct returns, the caller passes a hidden pointer as first arg
            if lambda_ret_ty in self.structs:
                self.local_var_offset -= 8
                self.local_vars['__ret_ptr'] = (self.local_var_offset, lambda_ret_ty + '*')
                reg = int_regs[int_idx]
                int_idx += 1
                lambda_text.append(f"    mov {reg}, {self.local_var_offset}(%rbp)")
            
            for pty, pname in params:
                if pty.startswith('float'):
                    self.local_var_offset -= 8
                    self.local_vars[pname] = (self.local_var_offset, pty)
                    reg = float_regs[float_idx]
                    float_idx += 1
                    if pty == 'float<32>':
                        lambda_text.append(f"    movss {reg}, {self.local_var_offset}(%rbp)")
                    else:
                        lambda_text.append(f"    movsd {reg}, {self.local_var_offset}(%rbp)")
                else:
                    self.local_var_offset -= 8
                    self.local_vars[pname] = (self.local_var_offset, pty)
                    reg = int_regs[int_idx]
                    int_idx += 1
                    lambda_text.append(f"    mov {reg}, {self.local_var_offset}(%rbp)")
            
            # Generate body
            self.text = lambda_text
            for stmt in body:
                self.gen_stmt(stmt)
            lambda_text = self.text
            
            # Add implicit return 0 if no return statement
            if not self.func_has_return:
                lambda_text.append("    mov $0, %eax")
                lambda_text.append("    leave")
                lambda_text.append("    ret")
            
            # Store lambda function for later emission
            self.lambda_funcs.append(lambda_text)
            
            # Restore state
            self.local_vars = saved_local_vars
            self.local_var_offset = saved_local_var_offset
            self.text = saved_text
            self.current_func_ret_ty = saved_func_ret_ty
            self.func_has_return = saved_func_has_return
            
            # Load lambda function address
            self.text.append(f"    lea {lambda_name}(%rip), %rax")
            return "fnptr"
        elif node[0] == 'cast':
            target_type = node[1]
            operand = node[2]
            src_ty = self.gen_expr(operand)  # generate operand code, get source type
            dst_ty = target_type
            if src_ty == dst_ty:
                return src_ty
            # Integer-like conversions (integer or pointer)
            if self._is_integer_like(src_ty) and self._is_integer_like(dst_ty):
                src_sz = self.sizeof(src_ty)
                dst_sz = self.sizeof(dst_ty)
                dst_signed = self._is_signed_type(dst_ty)
                # Source value is in %rax (already 64-bit extended)
                if dst_sz < 8:
                    if dst_sz == 4:
                        if dst_signed:
                            self.text.append("    movslq %eax, %rax")
                        else:
                            self.text.append("    movl %eax, %eax")
                    elif dst_sz == 2:
                        if dst_signed:
                            self.text.append("    movswq %ax, %rax")
                        else:
                            self.text.append("    movzwq %ax, %rax")
                    elif dst_sz == 1:
                        if dst_signed:
                            self.text.append("    movsbq %al, %rax")
                        else:
                            self.text.append("    movzbq %al, %rax")
                return dst_ty
            # Float to float conversion
            if src_ty.startswith('float') and dst_ty.startswith('float'):
                if src_ty in ('float<64>', 'float') and dst_ty == 'float<32>':
                    self.text.append("    cvtsd2ss %xmm0, %xmm0")
                elif src_ty == 'float<32>' and dst_ty in ('float<64>', 'float'):
                    self.text.append("    cvtss2sd %xmm0, %xmm0")
                return dst_ty
            # Integer to float
            if self._is_integer_like(src_ty) and dst_ty.startswith('float'):
                if dst_ty == 'float<32>':
                    self.text.append("    cvtsi2ss %rax, %xmm0")
                else:
                    self.text.append("    cvtsi2sd %rax, %xmm0")
                return dst_ty
            # Float to integer
            if src_ty.startswith('float') and self._is_integer_like(dst_ty):
                if src_ty == 'float<32>':
                    self.text.append("    cvttss2si %xmm0, %rax")
                else:
                    self.text.append("    cvttsd2si %xmm0, %rax")
                return dst_ty
            # Char to string
            if src_ty == 'char' and dst_ty in ('string', 'char*'):
                # Allocate 2 bytes, store char and null terminator
                self.text.append("    push %rax")
                self.text.append("    mov $2, %rdi")
                self.text.append("    call malloc@PLT")
                self.text.append("    mov %rax, %r11")
                self.text.append("    pop %rax")
                self.text.append("    movb %al, (%r11)")
                self.text.append("    movb $0, 1(%r11)")
                self.text.append("    mov %r11, %rax")
                return 'string'
            # String to char
            if src_ty in ('string', 'char*') and dst_ty == 'char':
                self.text.append("    movzbq (%rax), %rax")
                return 'char'
            # String to integer
            if src_ty in ('string', 'char*') and self._is_integer_type(dst_ty):
                # Call atoi: expects char* in %rdi, returns int in %rax
                self.text.append("    mov %rax, %rdi")
                self.text.append("    call atoi@PLT")
                # Extend the 32-bit result to the destination integer type size
                dst_sz = self.sizeof(dst_ty)
                dst_signed = self._is_signed_type(dst_ty)
                if dst_sz >= 8:
                    if dst_signed:
                        self.text.append("    movslq %eax, %rax")
                    else:
                        self.text.append("    movl %eax, %eax")
                elif dst_sz == 4:
                    if dst_signed:
                        self.text.append("    movslq %eax, %rax")
                    else:
                        self.text.append("    movl %eax, %eax")
                elif dst_sz == 2:
                    if dst_signed:
                        self.text.append("    movswq %ax, %rax")
                    else:
                        self.text.append("    movzwq %ax, %rax")
                elif dst_sz == 1:
                    if dst_signed:
                        self.text.append("    movsbq %al, %rax")
                    else:
                        self.text.append("    movzbq %al, %rax")
                return dst_ty
            # Integer to string
            if self._is_integer_type(src_ty) and dst_ty in ('string', 'char*'):
                # Allocate 16 bytes on stack to store integer and maintain alignment
                self.text.append("    sub $16, %rsp")  # allocate 16 bytes, keep stack aligned
                self.text.append("    mov %rax, 8(%rsp)")  # save integer at offset 8
                # Allocate buffer for string (32 bytes)
                self.text.append("    mov $32, %rdi")
                self.text.append("    call malloc@PLT")
                # Save buffer pointer in the stack slot at 0(%rsp)
                self.text.append("    mov %rax, (%rsp)")
                # Prepare arguments for sprintf
                self.text.append("    mov (%rsp), %rdi")  # buffer
                # Get or create format string for integer conversion
                if not self.int_format_label:
                    self.int_format_label = f".LC_INT_FMT{self.str_count}"
                    self.str_count += 1
                    self.rodata.append(f"{self.int_format_label}:")
                    self.rodata.append('    .string "%d"')
                self.text.append(f"    lea {self.int_format_label}(%rip), %rsi")  # format
                self.text.append("    mov 8(%rsp), %rdx")  # integer value
                self.text.append("    xor %al, %al")  # clear al for variadic function
                self.text.append("    call sprintf@PLT")
                # Result buffer pointer is at (%rsp)
                self.text.append("    mov (%rsp), %rax")  # return buffer pointer
                self.text.append("    add $16, %rsp")  # deallocate stack space
                return 'string'
            # If none of the above, unsupported
            raise Exception(f"Unsupported cast from {src_ty} to {dst_ty}")
        elif node[0] == 'unary':
            op, target = node[1], node[2]
            if op == '&':
                addr, ty = self.get_lvalue(target)
                self.text.append(f"    lea {addr}, %rax")
                return ty + '*'
            elif op == '*':
                ty = self.gen_expr(target)
                inner_ty = ty[:-1] if ty.endswith('*') else 'void'
                sz = self.sizeof(inner_ty)
                if inner_ty.startswith('float'):
                    if inner_ty == 'float<32>': self.text.append("    movss (%rax), %xmm0")
                    else: self.text.append("    movsd (%rax), %xmm0")
                else:
                    is_unsigned = inner_ty.startswith('unsigned ')
                    if sz == 1:
                        if is_unsigned:
                            self.text.append("    movzbq (%rax), %rax")
                        else:
                            self.text.append("    movsbq (%rax), %rax")
                    elif sz == 2:
                        if is_unsigned:
                            self.text.append("    movzwq (%rax), %rax")
                        else:
                            self.text.append("    movswq (%rax), %rax")
                    elif sz == 4:
                        if is_unsigned:
                            self.text.append("    movl (%rax), %eax")
                        else:
                            self.text.append("    movslq (%rax), %rax")
                    else:
                        self.text.append("    mov (%rax), %rax")
                return inner_ty
            elif op == '-':
                ty = self.gen_expr(target)
                if ty.startswith('float'):
                    self.text.append("    xorpd %xmm1, %xmm1")
                    if ty == 'float<32>': self.text.append("    subss %xmm0, %xmm1")
                    else: self.text.append("    subsd %xmm0, %xmm1")
                    self.text.append("    movaps %xmm1, %xmm0")
                else:
                    self.text.append("    neg %rax")
                return ty
            elif op == '~':
                ty = self.gen_expr(target)
                self.text.append("    not %rax")
                return ty
            elif op == '!':
                ty = self.gen_expr(target)
                self.text.append("    test %rax, %rax")
                self.text.append("    sete %al")
                self.text.append("    movzbq %al, %rax")
                return 'int'
            return "unknown"
        elif node[0] in ('id', 'member_access', 'arrow_access', 'array_access', 'namespace_access'):
            addr, ty = self.get_lvalue(node)
            sz = self.sizeof(ty)
            # For struct types, return the address as a pointer
            if ty in self.structs:
                if '(%r11)' in addr:
                    # Address is already in r11, move to rax
                    off = int(addr.split('(')[0]) if addr.split('(')[0] else 0
                    self.text.append(f"    lea {off}(%r11), %rax")
                elif '(%rbp)' in addr:
                    off = int(addr.split('(')[0])
                    self.text.append(f"    lea {off}(%rbp), %rax")
                elif '(%rax)' in addr:
                    off = int(addr.split('(')[0]) if addr.split('(')[0] else 0
                    self.text.append(f"    lea {off}(%rax), %rax")
                else:
                    self.text.append(f"    lea {addr}, %rax")
                return ty + '*'  # Return as pointer to struct
            elif ty.startswith('array<'):
                # For array types, return the address in %rax (treating as aggregate)
                if '(%r10)' in addr:
                    off = int(addr.split('(')[0]) if addr.split('(')[0] else 0
                    self.text.append(f"    lea {off}(%r10), %rax")
                elif '(%r11)' in addr:
                    # If address is already in r11 (from array access), return it in rax
                    # addr is "(%r11)" or "offset(%r11)"
                    if '(' in addr:
                        base = addr.split('(')[1][:-1]
                        off = addr.split('(')[0] if addr.split('(')[0] else "0"
                        self.text.append(f"    lea {off}(%{base}), %rax")
                    else:
                        self.text.append(f"    lea {addr}, %rax")
                elif '(%rbp)' in addr:
                    off = int(addr.split('(')[0])
                    self.text.append(f"    lea {off}(%rbp), %rax")
                elif '(%rax)' in addr:
                    off = int(addr.split('(')[0]) if addr.split('(')[0] else 0
                    self.text.append(f"    lea {off}(%rax), %rax")
                else:
                    self.text.append(f"    lea {addr}, %rax")
                return ty + '*'
            elif ty.startswith('float'):
                if ty == 'float<32>':
                    self.text.append(f"    movss {addr}, %xmm0")
                else:
                    self.text.append(f"    movsd {addr}, %xmm0")
            else:
                # Check if type is unsigned for proper extension
                is_unsigned = ty.startswith('unsigned ')
                base_ty = ty.split(' ', 1)[1] if is_unsigned else ty
                
                if sz == 1:
                    if is_unsigned:
                        self.text.append(f"    movzbq {addr}, %rax")
                    else:
                        self.text.append(f"    movsbq {addr}, %rax")
                elif sz == 2:
                    if is_unsigned:
                        self.text.append(f"    movzwq {addr}, %rax")
                    else:
                        self.text.append(f"    movswq {addr}, %rax")
                elif sz == 4:
                    if is_unsigned:
                        self.text.append(f"    movl {addr}, %eax")
                    else:
                        self.text.append(f"    movslq {addr}, %rax")
                else:
                    self.text.append(f"    mov {addr}, %rax")
            return ty
        elif node[0] == 'assign':
            left, right = node[1], node[2]
            
            # Special case for *ptr = ...
            if left[0] == 'unary' and left[1] == '*':
                self.gen_expr(left[2]) # Get address in %rax
                self.text.append("    push %rax")
                ty_r = self.gen_expr(right)
                self.text.append("    pop %rcx") # Address in %rcx, value in %rax
                if self._is_float(ty_r):
                    if ty_r == 'float<32>': self.text.append("    movss %xmm0, (%rcx)")
                    else: self.text.append("    movsd %xmm0, (%rcx)")
                else:
                    self.text.append("    mov %rax, (%rcx)")
                return ty_r

            addr, ty_l = self.get_lvalue(left)
            
            # If the address is dynamic (uses volatile registers), save it on stack
            addr_on_stack = False
            if any(reg in addr for reg in ['(%rax)', '(%r10)', '(%r11)']):
                self.text.append(f"    lea {addr}, %r10")
                self.text.append("    push %r10")
                addr_on_stack = True
                addr = "(%r10)" # Will be popped into r10

            if right[0] == 'init_list':
                self._gen_init_list_recursive(right, ty_l)
                if addr_on_stack: self.text.append("    pop %rdi")
                else: self.text.append(f"    lea {addr}, %rdi")
                self.text.append("    mov %rsp, %rsi")
                self.text.append(f"    mov ${self.sizeof(ty_l)}, %rdx")
                self.text.append("    call memcpy@PLT")
                self.text.append(f"    add ${self.sizeof(ty_l)}, %rsp")
                return ty_l
            
            if self._is_aggregate(ty_l):
                # Aggregate assignment or function return
                ty_r = self.gen_expr(right)
                if addr_on_stack: self.text.append("    pop %rdi")
                else: self.text.append(f"    lea {addr}, %rdi")
                
                # Check if ty_r is a value on stack or a pointer
                if self._returns_by_stack(ty_r):
                    # Result is on top of stack (from a function call)
                    self.text.append("    mov %rsp, %rsi")
                    self.text.append(f"    mov ${self.sizeof(ty_l)}, %rdx")
                    self.text.append("    call memcpy@PLT")
                    # Clean up the stack temporary
                    st_sz = self.sizeof(ty_l)
                    if st_sz % 16 != 0: st_sz += 16 - (st_sz % 16)
                    self.text.append(f"    add ${st_sz}, %rsp")
                else:
                    # Result is a pointer in rax
                    self.text.append("    mov %rax, %rsi")
                    self.text.append(f"    mov ${self.sizeof(ty_l)}, %rdx")
                    self.text.append("    call memcpy@PLT")
                return ty_l
            
            ty_r = self.gen_expr(right)
            if addr_on_stack:
                self.text.append("    pop %r10")
                addr = "(%r10)"
            if self._is_float(ty_l):
                if ty_l == 'float<32>':
                    if ty_r == 'float' or ty_r == 'float<64>': self.text.append("    cvtsd2ss %xmm0, %xmm0")
                    self.text.append(f"    movss %xmm0, {addr}")
                else:
                    if ty_r == 'float<32>': self.text.append("    cvtss2sd %xmm0, %xmm0")
                    self.text.append(f"    movsd %xmm0, {addr}")
            else:
                sz = self.sizeof(ty_l)
                if sz == 1: self.text.append(f"    mov %al, {addr}")
                elif sz == 2: self.text.append(f"    mov %ax, {addr}")
                elif sz == 4: self.text.append(f"    mov %eax, {addr}")
                else: self.text.append(f"    mov %rax, {addr}")
            return ty_l

        elif node[0] == 'binop':
            op = node[1]
            left = node[2]
            right = node[3]
            
            # Short-circuit logical operators
            if op in ('&&', '||'):
                # Evaluate left first
                self.gen_expr(left)  # result in %rax
                self.text.append("    test %rax, %rax")
                label_false = f".Lsc_false_{self.label_count}"
                label_end = f".Lsc_end_{self.label_count}"
                if op == '&&':
                    self.text.append(f"    je {label_false}")
                    # left is true, evaluate right
                    self.gen_expr(right)
                    # Convert to 0/1
                    self.text.append("    test %rax, %rax")
                    self.text.append("    setne %al")
                    self.text.append("    movzbq %al, %rax")
                    self.text.append(f"    jmp {label_end}")
                    self.text.append(f"{label_false}:")
                    self.text.append("    mov $0, %rax")
                    self.text.append(f"{label_end}:")
                else:  # '||'
                    self.text.append(f"    jne {label_end}")
                    # left is false, evaluate right
                    self.gen_expr(right)
                    self.text.append("    test %rax, %rax")
                    self.text.append("    setne %al")
                    self.text.append("    movzbq %al, %rax")
                    self.text.append(f"{label_end}:")
                self.label_count += 1
                return 'int'
            
            # Standard binary operators (non short-circuit)
            ty_r = self.gen_expr(right)
            if ty_r.startswith('float'):
                self.text.append("    sub $8, %rsp")
                if ty_r == 'float<32>':
                    self.text.append("    movss %xmm0, (%rsp)")
                else:
                    self.text.append("    movsd %xmm0, (%rsp)")
            else:
                self.text.append("    push %rax")
                
            ty_l = self.gen_expr(left)
            
            # Pointer arithmetic scaling
            ptr_scaling = 1
            is_ptr_sub = False
            if ty_l.endswith('*') and not ty_r.endswith('*'):
                target_ty = ty_l[:-1] if ty_l != 'void*' else 'int<8>'
                ptr_scaling = self.sizeof(target_ty)
            elif ty_r.endswith('*') and not ty_l.endswith('*'):
                target_ty = ty_r[:-1] if ty_r != 'void*' else 'int<8>'
                ptr_scaling = self.sizeof(target_ty)
            elif ty_l.endswith('*') and ty_r.endswith('*') and op == '-':
                target_ty = ty_l[:-1] if ty_l != 'void*' else 'int<8>'
                ptr_scaling = self.sizeof(target_ty)
                is_ptr_sub = True

            if ty_l == 'string' and ty_r == 'string':
                if op == '+':
                    self.text.append("    pop %rsi")
                    self.text.append("    mov %rax, %rdi")
                    self.text.append("    call __c5_str_add")
                    self.uses_str_add = True
                    return "string"
                elif op == '-':
                    self.text.append("    pop %rsi")
                    self.text.append("    mov %rax, %rdi")
                    self.text.append("    call __c5_str_sub")
                    self.uses_str_sub = True
                    return "string"
            
            if ty_l.startswith('float') or ty_r.startswith('float'):
                # Determine the float precision to use: prefer 64-bit if any operand is 64-bit
                use_64bit = False
                if ty_l.startswith('float') and ty_l != 'float<32>':
                    use_64bit = True
                if ty_r.startswith('float') and ty_r != 'float<32>':
                    use_64bit = True
                
                # Ensure left operand is in %xmm0 with correct precision
                if ty_l.startswith('float'):
                    if ty_l == 'float<32>' and use_64bit:
                        # Convert 32-bit to 64-bit
                        self.text.append("    cvtss2sd %xmm0, %xmm0")
                else:
                    # Left is integer, convert to float
                    if use_64bit:
                        self.text.append("    cvtsi2sd %rax, %xmm0")
                    else:
                        self.text.append("    cvtsi2ss %rax, %xmm0")
                
                # Load right operand into %xmm1, converting if necessary
                if ty_r.startswith('float'):
                    # Right operand is on stack as float
                    if ty_r == 'float<32>':
                        self.text.append("    movss (%rsp), %xmm1")
                    else:
                        self.text.append("    movsd (%rsp), %xmm1")
                    if ty_r == 'float<32>' and use_64bit:
                        self.text.append("    cvtss2sd %xmm1, %xmm1")
                    # Clean up stack allocation for float
                    self.text.append("    add $8, %rsp")
                else:
                    # Right operand is integer on stack (pushed earlier)
                    self.text.append("    pop %rax")  # get integer value into rax
                    if use_64bit:
                        self.text.append("    cvtsi2sd %rax, %xmm1")
                    else:
                        self.text.append("    cvtsi2ss %rax, %xmm1")
                
                # Perform the operation
                if op == '+':
                    if use_64bit:
                        self.text.append("    addsd %xmm1, %xmm0")
                    else:
                        self.text.append("    addss %xmm1, %xmm0")
                elif op == '-':
                    if use_64bit:
                        self.text.append("    subsd %xmm1, %xmm0")
                    else:
                        self.text.append("    subss %xmm1, %xmm0")
                elif op == '*':
                    if use_64bit:
                        self.text.append("    mulsd %xmm1, %xmm0")
                    else:
                        self.text.append("    mulss %xmm1, %xmm0")
                elif op == '/':
                    if use_64bit:
                        self.text.append("    divsd %xmm1, %xmm0")
                    else:
                        self.text.append("    divss %xmm1, %xmm0")
                elif op in ('==', '!=', '<', '>', '<=', '>='):
                    # Compare floats
                    if use_64bit:
                        self.text.append("    ucomisd %xmm1, %xmm0")
                    else:
                        self.text.append("    ucomiss %xmm1, %xmm0")
                    # Set result based on flags
                    if op == '==':
                        self.text.append("    sete %al")
                    elif op == '!=':
                        self.text.append("    setne %al")
                    elif op == '<':
                        self.text.append("    setb %al")    # below (CF=1)
                    elif op == '>':
                        self.text.append("    seta %al")    # above (CF=0 and ZF=0)
                    elif op == '<=':
                        self.text.append("    setbe %al")   # below or equal
                    elif op == '>=':
                        self.text.append("    setae %al")   # above or equal
                    self.text.append("    movzbq %al, %rax")
                    return 'int'
                else:
                    raise Exception(f"Unsupported operator {op} for floating-point types")
                
                # Return the appropriate float type
                if use_64bit:
                    # Return the 64-bit float type from the operands (prefer original 64-bit if any)
                    if ty_l.startswith('float') and ty_l != 'float<32>':
                        return ty_l
                    else:
                        return ty_r if ty_r.startswith('float') else 'float<64>'
                else:
                    # Return 32-bit float type
                    if ty_l.startswith('float') and ty_l == 'float<32>':
                        return ty_l
                    else:
                        return ty_r if ty_r.startswith('float') and ty_r == 'float<32>' else 'float<32>'
            else:
                self.text.append("    pop %rcx") # rcx is the right operand (pushed earlier)
                
                # Apply scaling for pointer arithmetic
                if ptr_scaling > 1:
                    if is_ptr_sub:
                        self.text.append(f"    sub %rcx, %rax")
                        self.text.append("    cqo")
                        self.text.append(f"    mov ${ptr_scaling}, %rcx")
                        self.text.append("    idiv %rcx")
                        return "int"
                    else:
                        if ty_l.endswith('*'):
                            self.text.append(f"    imul ${ptr_scaling}, %rcx")
                        else:
                            self.text.append(f"    imul ${ptr_scaling}, %rax")

                # Arithmetic operators
                if op == '+':
                    self.text.append("    add %rcx, %rax")
                elif op == '-':
                    self.text.append("    sub %rcx, %rax")
                elif op == '*':
                    self.text.append("    imul %rcx, %rax")
                elif op == '/':
                    self.text.append("    cqo")
                    self.text.append("    idiv %rcx")
                elif op == '%':
                    self.text.append("    cqo")
                    self.text.append("    idiv %rcx")
                    self.text.append("    mov %rdx, %rax")
                # Comparison operators
                elif op == '>':
                    self.text.append("    cmp %rcx, %rax")
                    if ty_l.startswith('unsigned '):
                        self.text.append("    seta %al")
                    else:
                        self.text.append("    setg %al")
                    self.text.append("    movzbq %al, %rax")
                elif op == '<':
                    self.text.append("    cmp %rcx, %rax")
                    if ty_l.startswith('unsigned '):
                        self.text.append("    setb %al")
                    else:
                        self.text.append("    setl %al")
                    self.text.append("    movzbq %al, %rax")
                elif op == '==':
                    self.text.append("    cmp %rcx, %rax")
                    self.text.append("    sete %al")
                    self.text.append("    movzbq %al, %rax")
                elif op == '!=':
                    self.text.append("    cmp %rcx, %rax")
                    self.text.append("    setne %al")
                    self.text.append("    movzbq %al, %rax")
                elif op == '>=':
                    self.text.append("    cmp %rcx, %rax")
                    if ty_l.startswith('unsigned '):
                        self.text.append("    setae %al")
                    else:
                        self.text.append("    setge %al")
                    self.text.append("    movzbq %al, %rax")
                elif op == '<=':
                    self.text.append("    cmp %rcx, %rax")
                    if ty_l.startswith('unsigned '):
                        self.text.append("    setbe %al")
                    else:
                        self.text.append("    setle %al")
                    self.text.append("    movzbq %al, %rax")
                # Bitwise operators
                elif op == '&':
                    self.text.append("    and %rcx, %rax")
                elif op == '|':
                    self.text.append("    or %rcx, %rax")
                elif op == '^':
                    self.text.append("    xor %rcx, %rax")
                # Shift operators
                elif op == '<<':
                    self.text.append("    shl %cl, %rax")
                elif op == '>>':
                    if ty_l.startswith('unsigned '):
                        self.text.append("    shr %cl, %rax")
                    else:
                        self.text.append("    sar %cl, %rax")
                return ty_l
        elif node[0] == 'call':
            target = node[1]
            args = node[2]
            
            # Handle method calls on arrays: arr.push(), arr.pop(), arr.length(), arr.clear()
            if target[0] == 'member_access':
                method = target[2]
                base = target[1]
                base_addr, base_ty = self.get_lvalue(base)
                if base_ty and base_ty.startswith('array<'):
                    elem_ty = self.array_elem_type(base_ty)
                    elem_sz = self.sizeof(elem_ty)
                    is_global = False
                    if '(%rbp)' in base_addr:
                        base_off = int(base_addr.split('(')[0])
                    elif '(%rip)' in base_addr:
                        # Global array: load address into r12 and use that as base
                        is_global = True
                        self.text.append(f"    lea {base_addr}, %r12")
                    else:
                        raise Exception("Arrays must be local or global variables")
                    
                    # Helper to generate array field access
                    def arr_ref(off):
                        if is_global:
                            return f"{off}(%r12)"
                        else:
                            return f"{base_off+off}(%rbp)"
                    
                    if method == 'push':
                        # For struct types, we need special handling
                        is_struct = elem_ty in self.structs or (elem_ty and elem_ty.startswith('array<')) or (elem_ty and elem_ty in self.types) or self.sizeof(elem_ty) > 8
                        
                        if is_struct:
                            # For structs, get the source address and use memcpy
                            if args[0][0] == 'init_list':
                                self._gen_init_list_recursive(args[0], elem_ty)
                                self.text.append("    mov %rsp, %r11")
                                self.text.append("    push %r11") # save src addr
                            else:
                                # Push from variable: get address of source struct
                                src_addr, src_ty = self.get_lvalue(args[0])
                                if '(%rbp)' in src_addr:
                                    src_off = int(src_addr.split('(')[0])
                                    self.text.append(f"    lea {src_off}(%rbp), %r11")
                                else:
                                    self.text.append(f"    lea {src_addr}, %r11")
                                self.text.append("    push %r11")  # save src addr
                        else:
                            # For primitive/enum types, evaluate and save value
                            self.gen_expr(args[0])
                            self.text.append("    push %rax")  # save value
                        
                        # Check if we need to grow: if len >= cap
                        self.label_count += 1
                        skip_grow = f".Lskip_grow_{self.label_count}"
                        self.text.append(f"    mov {arr_ref(8)}, %r10")   # len
                        self.text.append(f"    cmp {arr_ref(16)}, %r10")  # cmp len, cap
                        self.text.append(f"    jl {skip_grow}")
                        # Grow: new_cap = cap * 2 (or 4 if 0)
                        self.text.append(f"    mov {arr_ref(16)}, %rdi")
                        self.text.append("    shl $1, %rdi")
                        self.text.append("    cmp $4, %rdi")
                        self.label_count += 1
                        cap_ok = f".Lcap_ok_{self.label_count}"
                        self.text.append(f"    jge {cap_ok}")
                        self.text.append("    mov $4, %rdi")
                        self.text.append(f"{cap_ok}:")
                        self.text.append(f"    mov %rdi, {arr_ref(16)}")  # update cap
                        self.text.append(f"    imul ${elem_sz}, %rdi")
                        self.text.append(f"    mov {arr_ref(0)}, %rdi")     # old data ptr (1st arg for realloc)
                        self.text.append(f"    mov {arr_ref(16)}, %rsi")     # new cap
                        self.text.append(f"    imul ${elem_sz}, %rsi")      # size (2nd arg for realloc)
                        self.text.append("    sub $8, %rsp")   # align stack to 16-byte boundary before call
                        self.text.append("    call realloc@PLT")
                        self.text.append("    add $8, %rsp")
                        self.text.append(f"    mov %rax, {arr_ref(0)}")     # update data ptr
                        self.text.append(f"{skip_grow}:")
                        
                        # Store value at data[len]
                        if is_struct:
                            # Use memcpy to copy struct data
                            self.text.append("    pop %r11")  # restore src addr
                            self.text.append(f"    mov {arr_ref(0)}, %rdi")  # dest = data ptr
                            self.text.append(f"    mov {arr_ref(8)}, %r10") # current len
                            self.text.append(f"    imul ${elem_sz}, %r10")
                            self.text.append("    add %r10, %rdi")  # dest = data + len*elem_sz
                            self.text.append("    mov %r11, %rsi")  # src
                            self.text.append(f"    mov ${elem_sz}, %rdx")  # size
                            self.text.append("    sub $8, %rsp")
                            self.text.append("    call memcpy@PLT")
                            self.text.append("    add $8, %rsp")
                            if args[0][0] == 'init_list':
                                # Restore stack after temp struct
                                self.text.append(f"    add ${self.sizeof(elem_ty)}, %rsp")
                        else:
                            self.text.append("    pop %rax")  # restore value
                            self.text.append(f"    mov {arr_ref(0)}, %rcx")  # data ptr
                            self.text.append(f"    mov {arr_ref(8)}, %r10") # current len
                            self.text.append(f"    imul ${elem_sz}, %r10")
                            self.text.append("    add %r10, %rcx")
                            if elem_sz == 1:
                                self.text.append("    mov %al, (%rcx)")
                            elif elem_sz == 2:
                                self.text.append("    mov %ax, (%rcx)")
                            elif elem_sz == 4:
                                self.text.append("    mov %eax, (%rcx)")
                            else:
                                self.text.append("    mov %rax, (%rcx)")
                        # Increment length
                        self.text.append(f"    incq {arr_ref(8)}")
                        return 'void'
                    
                    elif method == 'pop':
                        # Decrement length, return data[new_len]
                        is_struct = elem_ty in self.structs or (elem_ty and elem_ty.startswith('array<')) or (elem_ty and elem_ty in self.types) or self.sizeof(elem_ty) > 8
                        self.text.append(f"    decq {arr_ref(8)}")
                        self.text.append(f"    mov {arr_ref(8)}, %r10") # new len
                        self.text.append(f"    mov {arr_ref(0)}, %rcx")   # data ptr
                        self.text.append(f"    imul ${elem_sz}, %r10")
                        self.text.append("    add %r10, %rcx")
                        if is_struct:
                            # For structs, return pointer to element in rax
                            # The element is still in the array buffer, just past the new length
                            self.text.append("    mov %rcx, %rax")
                        else:
                            if elem_sz == 1:
                                self.text.append("    movzbq (%rcx), %rax")
                            elif elem_sz == 2:
                                self.text.append("    movzwq (%rcx), %rax")
                            elif elem_sz == 4:
                                self.text.append("    movslq (%rcx), %rax")
                            else:
                                self.text.append("    mov (%rcx), %rax")
                        return elem_ty
                    
                    elif method == 'length':
                        self.text.append(f"    mov {arr_ref(8)}, %rax")
                        return 'int'
                    
                    elif method == 'clear':
                        self.text.append(f"    movq $0, {arr_ref(8)}")
                        return 'void'
                elif base_ty and (base_ty == 'string' or base_ty == 'char*'):
                    if method == 'length':
                        if '(%rbp)' in base_addr:
                            off = int(base_addr.split('(')[0])
                            self.text.append(f"    mov {off}(%rbp), %rdi")
                        elif '(%rip)' in base_addr:
                            self.text.append(f"    mov {base_addr}, %rdi")
                        else:
                            self.text.append(f"    mov {base_addr}, %rdi")
                        self.text.append("    call strlen@PLT")
                        return 'int'
                    if method == 'replace':
                        # Load base string pointer into %rdi
                        if '(%rbp)' in base_addr:
                            off = int(base_addr.split('(')[0])
                            self.text.append(f"    mov {off}(%rbp), %rdi")
                        elif '(%rip)' in base_addr:
                            self.text.append(f"    mov {base_addr}, %rdi")
                        else:
                            self.text.append(f"    mov {base_addr}, %rdi")
                        # Save base pointer on stack
                        self.text.append("    push %rdi")
                        # Generate first argument (old) -> %rsi
                        ty_arg0 = self.gen_expr(args[0])
                        self.text.append("    mov %rax, %rsi")
                        # Generate second argument (new) -> %rdx
                        ty_arg1 = self.gen_expr(args[1])
                        self.text.append("    mov %rax, %rdx")
                        # Restore base pointer into %rdi
                        self.text.append("    pop %rdi")
                        # Call helper
                        self.text.append("    call __c5_str_replace")
                        self.uses_str_replace = True
                        return 'string'
                
                raise Exception(f"Unknown method {method} on type {base_ty}")

            
            # Handle built-in c_str() function
            if target[0] == 'id' and target[1] == 'c_str':
                # c_str() takes a string argument and returns char* (the same pointer)
                if len(args) == 1:
                    ty = self.gen_expr(args[0])
                    # The result is already in %rax - for strings, it's already a char*
                    return 'char*'
            
            func_name = ""
            full_func_name = ""
            is_func_ptr_call = False
            func_ptr_ret_ty = None  # Track return type for function pointers
            
            if target[0] == 'namespace_access':
                full_func_name = f"{target[1]}::{target[2]}"
                func_name = target[2]
            elif target[0] == 'id':
                func_name = target[1]
                full_func_name = func_name
                # Check if this is a function pointer variable (lambda)
                if func_name in self.local_vars:
                    var_info = self.local_vars[func_name]
                    # Check if it's a lambda variable (tuple with 3 elements)
                    if len(var_info) >= 3 and var_info[2] == True:
                        func_ptr_ret_ty = var_info[1]  # Get the return type
                    is_func_ptr_call = True
            
            # Check if the function returns an array or struct type
            ret_ty = "int"
            if is_func_ptr_call and func_ptr_ret_ty:
                ret_ty = func_ptr_ret_ty
            elif full_func_name in self.func_signatures:
                ret_ty = self.func_signatures[full_func_name]
            elif func_name in self.func_signatures:
                ret_ty = self.func_signatures[func_name]
            
            is_vararg = False
            if full_func_name in self.extern_funcs and self.extern_funcs[full_func_name]['varargs']:
                is_vararg = True
            elif func_name in self.extern_funcs and self.extern_funcs[func_name]['varargs']:
                is_vararg = True
            
            # For struct returns, allocate space on stack for the return value BEFORE pushing args
            # This way the struct space will be at the bottom of the stack after all pops
            if self._returns_by_stack(ret_ty):
                st_sz = self.sizeof(ret_ty)
                # Align to 16 bytes
                if st_sz % 16 != 0:
                    st_sz += 16 - (st_sz % 16)
                self.text.append(f"    sub ${st_sz}, %rsp")
            
            # For array arguments, pass the 3 fields (ptr, len, cap)
            # For struct arguments, pass in registers if <= 16 bytes, otherwise by pointer
            arg_types = []
            
            for arg in args:
                if arg[0] == 'init_list':
                    # Inline init_list passed as function arg
                    # We need to know the expected type from function signature
                    param_ty = None
                    for fnode in [n for n in self._current_ast if n[0] == 'func' and n[2] == func_name]:
                        params = fnode[3]
                        idx = len(arg_types)
                        if idx < len(params):
                            param_ty = params[idx][0]
                    
                    items = arg[1]
                    count = len(items)
                    
                    # Check if this is a struct initializer
                    if param_ty and param_ty in self.structs:
                        # Struct initializer: create temp struct, then pass in registers
                        st = self.structs[param_ty]
                        st_sz = st['size']
                        field_list = list(st['fields'].items())
                        
                        # Allocate temp space on stack (aligned to 8)
                        st_sz_aligned = st_sz
                        if st_sz % 8 != 0:
                            st_sz_aligned = st_sz + (8 - st_sz % 8)
                        self.text.append(f"    sub ${st_sz_aligned}, %rsp")
                        
                        # Initialize fields
                        for fi, fval in enumerate(items):
                            fname, finfo = field_list[fi]
                            self.gen_expr(fval)
                            foff = finfo['offset']
                            if finfo['type'].startswith('float'):
                                if finfo['type'] == 'float<32>':
                                    self.text.append(f"    movss %xmm0, {foff}(%rsp)")
                                else:
                                    self.text.append(f"    movsd %xmm0, {foff}(%rsp)")
                            else:
                                fsz = self.sizeof(finfo['type'])
                                if fsz == 1:
                                    self.text.append(f"    mov %al, {foff}(%rsp)")
                                elif fsz == 2:
                                    self.text.append(f"    mov %ax, {foff}(%rsp)")
                                elif fsz == 4:
                                    self.text.append(f"    mov %eax, {foff}(%rsp)")
                                else:
                                    self.text.append(f"    mov %rax, {foff}(%rsp)")
                        
                        # Now load struct values and push for register passing
                        if st_sz <= 16:
                            # We need to push values so they pop into correct registers
                            # pop order in generated code: pop %rsi, pop %rdi
                            # So push order: first value (for rdi), then second value (for rsi)
                            
                            # Save the base of our temp struct
                            self.text.append("    mov %rsp, %r11")  # r11 = base of temp struct
                            
                            # Push first 8 bytes (will be popped second -> rdi)
                            self.text.append(f"    mov (%r11), %rax")
                            self.text.append("    push %rax")
                            if st_sz > 8:
                                # Push second 8 bytes (will be popped first -> rsi)
                                self.text.append(f"    mov 8(%r11), %rax")
                                self.text.append("    push %rax")
                            
                            # Don't clean up temp space here - leave it on stack
                            # It will be cleaned up after the function call
                            arg_types.append(param_ty)
                        else:
                            # Pass pointer to struct
                            self.text.append("    mov %rsp, %rax")
                            self.text.append("    push %rax")
                            arg_types.append(param_ty)
                            
                    elif param_ty and param_ty.startswith('array<'):
                        # Array initializer
                        a_elem_ty = self.array_elem_type(param_ty)
                        a_elem_sz = self.sizeof(a_elem_ty)
                        alloc_sz = count * a_elem_sz
                        # malloc
                        self.text.append(f"    mov ${alloc_sz}, %rdi")
                        self.text.append("    call malloc@PLT")
                        self.text.append("    push %rax")  # save data ptr temporarily
                        # Fill elements
                        for i, val in enumerate(items):
                            self.gen_expr(val)
                            self.text.append("    mov 0(%rsp), %rcx")  # peek data ptr
                            off = i * a_elem_sz
                            if a_elem_sz == 4:
                                self.text.append(f"    mov %eax, {off}(%rcx)")
                            else:
                                self.text.append(f"    mov %rax, {off}(%rcx)")
                        # Pop data ptr, then push in LIFO order for correct register assignment
                        self.text.append("    pop %r11")  # data ptr in r11
                        self.text.append(f"    mov ${count}, %rax")
                        self.text.append("    push %rax")    # push cap (will be popped last -> rdx)
                        self.text.append(f"    mov ${count}, %rax")
                        self.text.append("    push %rax")    # push len (will be popped 2nd -> rsi)
                        self.text.append("    push %r11")    # push ptr (will be popped 1st -> rdi)
                        arg_types.append(param_ty)
                    else:
                        # Unknown type - treat as int
                        for val in items:
                            self.gen_expr(val)
                            self.text.append("    push %rax")
                        arg_types.append('int')
                else:
                    ty = self.gen_expr(arg)
                    if ty.startswith('float'):
                        self.text.append("    sub $8, %rsp")
                        if ty == 'float<32>':
                            self.text.append("    movss %xmm0, (%rsp)")
                        else:
                            self.text.append("    movsd %xmm0, (%rsp)")
                        arg_types.append(ty)
                    elif ty.startswith('array<'):
                        # Push array fields in LIFO order: cap, len, ptr
                        # The expression returned the address of the 24-byte header in %rax
                        self.text.append("    pushq 16(%rax)")  # cap (popped last)
                        self.text.append("    pushq 8(%rax)")   # len (popped 2nd)
                        self.text.append("    pushq (%rax)")    # ptr (popped 1st)
                        arg_types.append(ty)
                    elif ty in self.structs:
                        # Struct argument: ty is the struct type (not pointer)
                        # The expression returned a pointer to the struct in %rax
                        st = self.structs[ty]
                        st_sz = st['size']
                        
                        if st_sz <= 16:
                            # Load struct values from pointer and push for register passing
                            self.text.append("    mov (%rax), %rcx")  # first 8 bytes
                            self.text.append("    push %rcx")
                            if st_sz > 8:
                                self.text.append("    mov 8(%rax), %rcx")  # second 8 bytes
                                self.text.append("    push %rcx")
                            arg_types.append(ty)
                        else:
                            # Pass pointer to struct
                            self.text.append("    push %rax")
                            arg_types.append(ty)
                    elif ty.endswith('*') and ty[:-1] in self.structs:
                        # Struct pointer argument - just pass the pointer
                        self.text.append("    push %rax")
                        arg_types.append(ty)
                    else:
                        self.text.append("    push %rax")
                        arg_types.append(ty)
                
            int_regs = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
            float_regs = ["%xmm0", "%xmm1", "%xmm2", "%xmm3", "%xmm4", "%xmm5"]
            
            # For arrays, we need 3 int regs per array arg
            # For structs <= 16 bytes, we need up to 2 int regs
            # For structs > 16 bytes, we need 1 int reg (pointer)
            # Count how many int regs we need for actual args
            int_slots = 0
            float_slots = 0
            for ty in arg_types:
                if ty.startswith('float'):
                    float_slots += 1
                elif ty.startswith('array<'):
                    int_slots += 3  # ptr, len, cap
                elif ty in self.structs:
                    st_sz = self.structs[ty]['size']
                    if st_sz <= 16:
                        int_slots += 2 if st_sz > 8 else 1
                    else:
                        int_slots += 1  # pointer
                else:
                    int_slots += 1
            
            # For struct returns, args start from %rsi (skip %rdi for hidden pointer)
            # So we need to shift register indices
            reg_offset = 1 if self._returns_by_stack(ret_ty) else 0
            
            int_idx = int_slots - 1 + reg_offset
            float_idx = float_slots - 1
            
            for ty in reversed(arg_types):
                if ty.startswith('float'):
                    reg = float_regs[float_idx]
                    float_idx -= 1
                    if is_vararg and ty == 'float<32>':
                        self.text.append(f"    movss (%rsp), %xmm0")
                        self.text.append(f"    cvtss2sd %xmm0, {reg}")
                    else:
                        if ty == 'float<32>':
                            self.text.append(f"    movss (%rsp), {reg}")
                        else:
                            self.text.append(f"    movsd (%rsp), {reg}")
                    self.text.append("    add $8, %rsp")
                elif ty.startswith('array<'):
                    # Pop 3 values: ptr, len, cap
                    reg_ptr = int_regs[int_idx - 2]
                    reg_len = int_regs[int_idx - 1]
                    reg_cap = int_regs[int_idx]
                    int_idx -= 3
                    self.text.append(f"    pop {reg_ptr}")   # ptr
                    self.text.append(f"    pop {reg_len}")   # len
                    self.text.append(f"    pop {reg_cap}")   # cap
                elif ty in self.structs:
                    # Struct argument: pop into registers
                    st_sz = self.structs[ty]['size']
                    if st_sz <= 16:
                        if st_sz > 8:
                            # Pop 2 values
                            reg2 = int_regs[int_idx]
                            int_idx -= 1
                            reg1 = int_regs[int_idx]
                            int_idx -= 1
                            self.text.append(f"    pop {reg2}")   # second 8 bytes
                            self.text.append(f"    pop {reg1}")   # first 8 bytes
                        else:
                            # Pop 1 value
                            reg = int_regs[int_idx]
                            int_idx -= 1
                            self.text.append(f"    pop {reg}")
                    else:
                        # Pop pointer
                        reg = int_regs[int_idx]
                        int_idx -= 1
                        self.text.append(f"    pop {reg}")
                else:
                    reg = int_regs[int_idx]
                    int_idx -= 1
                    self.text.append(f"    pop {reg}")

            # For struct returns, allocate space and load hidden pointer into %rdi
            if self._returns_by_stack(ret_ty):
                st_sz = self.sizeof(ret_ty)
                # Align to 16 bytes
                if st_sz % 16 != 0: st_sz += 16 - (st_sz % 16)
                self.text.append(f"    sub ${st_sz}, %rsp")
                self.text.append(f"    mov %rsp, %rdi")  # Hidden pointer in %rdi

            if is_vararg:
                float_count = len([ty for ty in arg_types if ty and ty.startswith('float')])
                self.text.append(f"    mov ${float_count}, %eax")
            
            if is_func_ptr_call:
                # Load function pointer from variable and call through it
                offset = self.local_vars[func_name][0]
                self.text.append(f"    mov {offset}(%rbp), %r11")
                self.text.append("    call *%r11")
            else:
                self.text.append(f"    call {func_name}@PLT")
            
            # For struct returns, the result is in the hidden pointer location (top of stack)
            # Return current stack pointer in rax and the base type (indicating it's on stack)
            if self._returns_by_stack(ret_ty):
                self.text.append("    mov %rsp, %rax")
                return ret_ty
            
            return ret_ty
