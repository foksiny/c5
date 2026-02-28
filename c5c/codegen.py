class CodeGen:
    def __init__(self, optimizer=None):
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
        self.lambda_count = 0
        self.lambda_funcs = []  # Store lambda function definitions
        self.break_targets = []  # Stack of break jump targets (for loops and switches)

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
                if base_ty.startswith('array<'):
                    if method == 'length':
                        return 'int'
                    if method == 'pop':
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
        
        safe_val = val.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r')
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
            raise Exception(f"Unknown namespaced var {name}")
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
            if ty.endswith('*'):
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
            
        out.append('.section .note.GNU-stack,"",@progbits')
        return "\n".join(out) + "\n"
        
    def _get_str_add_asm(self):
        return """
.global __c5_str_add
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
        self.text.append("    sub $512, %rsp")
        
        int_regs = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
        float_regs = ["%xmm0", "%xmm1", "%xmm2", "%xmm3", "%xmm4", "%xmm5"]
        int_idx = 0
        float_idx = 0
        
        # For struct returns, the caller passes a hidden pointer as first arg
        if ty in self.structs:
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
            self.gen_expr(node[1])
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
            
            # Zero-initialize arrays when declared without initializer
            if ty.startswith('array<') and not init_expr:
                base_off = self.local_var_offset
                self.text.append(f"    movq $0, {base_off}(%rbp)")       # data ptr = NULL
                self.text.append(f"    movq $0, {base_off+8}(%rbp)")     # length = 0
                self.text.append(f"    movq $0, {base_off+16}(%rbp)")    # capacity = 0
            
            if init_expr:
                # Set expected return type for lambda expressions
                if init_expr[0] == 'lambda':
                    self.lambda_ret_type = ty
                
                if init_expr[0] == 'init_list':
                    if ty.startswith('array<'):
                        # Array init from init_list: allocate, set len/cap, copy data
                        elem_ty = self.array_elem_type(ty)
                        elem_sz = self.sizeof(elem_ty)
                        items = init_expr[1]
                        count = len(items)
                        alloc_sz = count * elem_sz
                        base_off = self.local_var_offset
                        # malloc for data
                        self.text.append(f"    mov ${alloc_sz}, %rdi")
                        self.text.append("    call malloc@PLT")
                        self.text.append(f"    mov %rax, {base_off}(%rbp)")       # data ptr
                        self.text.append(f"    movq ${count}, {base_off+8}(%rbp)")  # length
                        self.text.append(f"    movq ${count}, {base_off+16}(%rbp)") # capacity
                        # Fill elements
                        for i, val in enumerate(items):
                            off = i * elem_sz
                            if val[0] == 'init_list' and elem_ty in self.structs:
                                # Struct initializer: fill fields directly in array memory
                                st = self.structs[elem_ty]
                                field_list = list(st['fields'].items())
                                for fi, fval in enumerate(val[1]):
                                    fname, finfo = field_list[fi]
                                    self.gen_expr(fval)
                                    self.text.append(f"    mov {base_off}(%rbp), %rcx")  # reload data ptr
                                    foff = off + finfo['offset']
                                    if finfo['type'].startswith('float'):
                                        if finfo['type'] == 'float<32>':
                                            self.text.append(f"    movss %xmm0, {foff}(%rcx)")
                                        else:
                                            self.text.append(f"    movsd %xmm0, {foff}(%rcx)")
                                    else:
                                        fsz = self.sizeof(finfo['type'])
                                        if fsz == 1:
                                            self.text.append(f"    mov %al, {foff}(%rcx)")
                                        elif fsz == 2:
                                            self.text.append(f"    mov %ax, {foff}(%rcx)")
                                        elif fsz == 4:
                                            self.text.append(f"    mov %eax, {foff}(%rcx)")
                                        else:
                                            self.text.append(f"    mov %rax, {foff}(%rcx)")
                            else:
                                # Primitive or enum element
                                self.gen_expr(val)
                                self.text.append(f"    mov {base_off}(%rbp), %rcx")  # reload data ptr
                                if elem_sz == 1:
                                    self.text.append(f"    mov %al, {off}(%rcx)")
                                elif elem_sz == 2:
                                    self.text.append(f"    mov %ax, {off}(%rcx)")
                                elif elem_sz == 4:
                                    self.text.append(f"    mov %eax, {off}(%rcx)")
                                else:
                                    self.text.append(f"    mov %rax, {off}(%rcx)")
                    elif ty in self.structs:
                        st = self.structs[ty]
                        field_list = list(st['fields'].items())
                        for i, init_val in enumerate(init_expr[1]):
                            fname, finfo = field_list[i]
                            foffset = self.local_var_offset + finfo['offset']
                            ret_ty = self.gen_expr(init_val)
                            
                            if finfo['type'].startswith('float'):
                                if finfo['type'] == 'float<32>':
                                    self.text.append(f"    movss %xmm0, {foffset}(%rbp)")
                                else:
                                    self.text.append(f"    movsd %xmm0, {foffset}(%rbp)")
                            else:
                                fsz = self.sizeof(finfo['type'])
                                if fsz == 1:
                                    self.text.append(f"    mov %al, {foffset}(%rbp)")
                                elif fsz == 2:
                                    self.text.append(f"    mov %ax, {foffset}(%rbp)")
                                elif fsz == 4:
                                    self.text.append(f"    mov %eax, {foffset}(%rbp)")
                                else:
                                    self.text.append(f"    mov %rax, {foffset}(%rbp)")
                else:
                    ret_ty = self.gen_expr(init_expr)
                    if ret_ty == 'fnptr':
                        # Lambda expression - always store as 8-byte pointer
                        self.text.append(f"    mov %rax, {self.local_var_offset}(%rbp)")
                        # Clean up lambda return type
                        if hasattr(self, 'lambda_ret_type'):
                            delattr(self, 'lambda_ret_type')
                    elif ret_ty and ret_ty.endswith('*') and ret_ty[:-1] in self.structs and not ty.endswith('*'):
                        # Function returns a struct pointer - copy to variable
                        # But only if the declared type is NOT a pointer (i.e., we want the struct value)
                        struct_ty = ret_ty[:-1]
                        st_sz = self.sizeof(struct_ty)
                        # ret_ty is a pointer to the struct in %rax
                        # Copy from %rax to local_var_offset
                        self.text.append("    mov %rax, %rsi")  # src
                        self.text.append(f"    lea {self.local_var_offset}(%rbp), %rdi")  # dest
                        self.text.append(f"    mov ${st_sz}, %rdx")
                        self.text.append("    call memcpy@PLT")
                    elif ty.startswith('float'):
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
                        fsz = self.sizeof(ty)
                        if fsz == 1:
                            self.text.append(f"    mov %al, {self.local_var_offset}(%rbp)")
                        elif fsz == 2:
                            self.text.append(f"    mov %ax, {self.local_var_offset}(%rbp)")
                        elif fsz == 4:
                            self.text.append(f"    mov %eax, {self.local_var_offset}(%rbp)")
                        else:
                            self.text.append(f"    mov %rax, {self.local_var_offset}(%rbp)")
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
                if func_ret_ty in self.structs:
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
                
                self.gen_expr(ret_expr)
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
            elem_sz = self.sizeof(elem_ty)
            
            # Check if element type is a struct
            is_struct = elem_ty in self.structs
            
            # Check if array_expr is a simple variable reference
            is_global_array = False
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
                self.text.append(f"    mov %rax, {array_off}(%rbp)")       # data ptr
                self.text.append(f"    mov %rdx, {array_off+8}(%rbp)")     # length
                self.text.append(f"    mov %rcx, {array_off+16}(%rbp)")    # capacity
            
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
            
            # Allocate value variable - use actual element size for structs
            if is_struct:
                # Align to 8 bytes
                if abs(self.local_var_offset) % 8 != 0:
                    self.local_var_offset -= 8 - (abs(self.local_var_offset) % 8)
                self.local_var_offset -= elem_sz
            else:
                self.local_var_offset -= 8
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
            if is_struct:
                # Use memcpy for struct types
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
        elif node[0] == 'namespace_access':
            base, name = node[1], node[2]
            namespaced_name = f"{base}::{name}"
            mangled = self.mangle(namespaced_name)
            if base in self.enums and name in self.enums[base]:
                val = self.enums[base][name]
                self.text.append(f"    mov ${val}, %rax")
                return "int"
            elif namespaced_name in self.global_vars:
                ty = self.global_vars[namespaced_name]
                sz = self.sizeof(ty)
                if ty.startswith('float'):
                   if ty == 'float<32>': self.text.append(f"    movss {mangled}(%rip), %xmm0")
                   else: self.text.append(f"    movsd {mangled}(%rip), %xmm0")
                else:
                    is_unsigned = ty.startswith('unsigned ')
                    if sz == 1:
                        if is_unsigned: self.text.append(f"    movzbq {mangled}(%rip), %rax")
                        else: self.text.append(f"    movsbq {mangled}(%rip), %rax")
                    elif sz == 2:
                        if is_unsigned: self.text.append(f"    movzwq {mangled}(%rip), %rax")
                        else: self.text.append(f"    movswq {mangled}(%rip), %rax")
                    elif sz == 4:
                        if is_unsigned: self.text.append(f"    movl {mangled}(%rip), %eax")
                        else: self.text.append(f"    movslq {mangled}(%rip), %rax")
                    else:
                        self.text.append(f"    mov {mangled}(%rip), %rax")
                return ty
            elif namespaced_name in self.func_signatures:
                self.text.append(f"    lea {mangled}(%rip), %rax")
                return "fnptr"
            else:
                raise Exception(f"Unknown namespace access: {namespaced_name}")
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
            lambda_text.append("    sub $512, %rsp")
            
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
                    # Check if type is unsigned for proper extension
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
            return "unknown"
        elif node[0] in ('id', 'member_access', 'arrow_access', 'array_access'):
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
                sz = 8
                if ty_r.startswith('float'):
                    if ty_r == 'float<32>': self.text.append("    movss %xmm0, (%rcx)")
                    else: self.text.append("    movsd %xmm0, (%rcx)")
                else:
                    self.text.append("    mov %rax, (%rcx)")
                return ty_r

            # Special case for array_access assignment: arr[i] = val
            if left[0] == 'array_access':
                addr, ty_l = self.get_lvalue(left)  # elem address in (%r11)
                is_struct = ty_l in self.structs
                
                if is_struct:
                    # For struct assignment, use memcpy
                    # Get source address
                    if right[0] == 'init_list':
                        # Struct initializer: create temp struct on stack
                        st = self.structs[ty_l]
                        st_sz = self.sizeof(ty_l)
                        self.text.append(f"    sub ${st_sz}, %rsp")
                        field_list = list(st['fields'].items())
                        for fi, fval in enumerate(right[1]):
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
                        self.text.append("    mov %rsp, %rsi")  # src
                    else:
                        # Get address of source struct
                        src_addr, src_ty = self.get_lvalue(right)
                        if '(%rbp)' in src_addr:
                            src_off = int(src_addr.split('(')[0])
                            self.text.append(f"    lea {src_off}(%rbp), %rsi")
                        elif '(%r11)' in src_addr:
                            off = int(src_addr.split('(')[0]) if src_addr.split('(')[0] else 0
                            self.text.append(f"    lea {off}(%r11), %rsi")
                        else:
                            self.text.append(f"    lea {src_addr}, %rsi")
                    
                    # Get dest address (element is at (%r11))
                    self.text.append("    mov %r11, %rdi")  # dest
                    self.text.append(f"    mov ${self.sizeof(ty_l)}, %rdx")  # size
                    self.text.append("    call memcpy@PLT")
                    
                    if right[0] == 'init_list':
                        st_sz = self.sizeof(ty_l)
                        self.text.append(f"    add ${st_sz}, %rsp")
                    return ty_l
                else:
                    ty_r = self.gen_expr(right)
                    self.text.append("    push %rax")  # save value
                    self.text.append("    pop %rax")
                    fsz = self.sizeof(ty_l)
                    if fsz == 1:
                        self.text.append(f"    mov %al, {addr}")
                    elif fsz == 2:
                        self.text.append(f"    mov %ax, {addr}")
                    elif fsz == 4:
                        self.text.append(f"    mov %eax, {addr}")
                    else:
                        self.text.append(f"    mov %rax, {addr}")
                    return ty_r

            # Special case for arrow_access assignment: ptr->field = val
            if left[0] == 'arrow_access':
                # First get the struct pointer into %rax, save to %r11
                addr, ty_l = self.get_lvalue(left)  # ptr in %rax, addr is offset(%rax)
                self.text.append("    mov %rax, %r11")  # save struct ptr
                ty_r = self.gen_expr(right)  # value in %rax
                # Reconstruct the address using %r11
                fixed_addr = addr.replace('%rax', '%r11')
                fsz = self.sizeof(ty_l)
                if ty_l.startswith('float'):
                    if ty_l == 'float<32>':
                        self.text.append(f"    movss %xmm0, {fixed_addr}")
                    else:
                        self.text.append(f"    movsd %xmm0, {fixed_addr}")
                else:
                    if fsz == 1:
                        self.text.append(f"    mov %al, {fixed_addr}")
                    elif fsz == 2:
                        self.text.append(f"    mov %ax, {fixed_addr}")
                    elif fsz == 4:
                        self.text.append(f"    mov %eax, {fixed_addr}")
                    else:
                        self.text.append(f"    mov %rax, {fixed_addr}")
                return ty_r

            # Special case for member_access assignment where base is array_access: arr[i].field = val
            if left[0] == 'member_access' and left[1][0] == 'array_access':
                ty_r = self.gen_expr(right)
                self.text.append("    push %rax")  # save value
                addr, ty_l = self.get_lvalue(left)  # this computes address in r11
                self.text.append("    pop %rax")  # restore value
                fsz = self.sizeof(ty_l)
                if ty_l.startswith('float'):
                    if ty_l == 'float<32>':
                        self.text.append(f"    movss %xmm0, {addr}")
                    else:
                        self.text.append(f"    movsd %xmm0, {addr}")
                else:
                    if fsz == 1:
                        self.text.append(f"    mov %al, {addr}")
                    elif fsz == 2:
                        self.text.append(f"    mov %ax, {addr}")
                    elif fsz == 4:
                        self.text.append(f"    mov %eax, {addr}")
                    else:
                        self.text.append(f"    mov %rax, {addr}")
                return ty_r

            # Check if left side is a struct type
            addr, ty_l = self.get_lvalue(left)
            is_struct = ty_l in self.structs
            
            if is_struct:
                # For struct assignment, use memcpy
                if right[0] == 'init_list':
                    # Struct initializer: create temp struct on stack
                    st = self.structs[ty_l]
                    st_sz = self.sizeof(ty_l)
                    self.text.append(f"    sub ${st_sz}, %rsp")
                    field_list = list(st['fields'].items())
                    for fi, fval in enumerate(right[1]):
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
                    self.text.append("    mov %rsp, %rsi")  # src
                    # Get dest address
                    if '(%rbp)' in addr:
                        off = int(addr.split('(')[0])
                        self.text.append(f"    lea {off}(%rbp), %rdi")
                    else:
                        self.text.append(f"    lea {addr}, %rdi")
                    self.text.append(f"    mov ${st_sz}, %rdx")
                    self.text.append("    call memcpy@PLT")
                    self.text.append(f"    add ${st_sz}, %rsp")
                else:
                    # Assign from another struct variable
                    src_addr, src_ty = self.get_lvalue(right)
                    if '(%rbp)' in src_addr:
                        src_off = int(src_addr.split('(')[0])
                        self.text.append(f"    lea {src_off}(%rbp), %rsi")
                    else:
                        self.text.append(f"    lea {src_addr}, %rsi")
                    # Get dest address
                    if '(%rbp)' in addr:
                        off = int(addr.split('(')[0])
                        self.text.append(f"    lea {off}(%rbp), %rdi")
                    else:
                        self.text.append(f"    lea {addr}, %rdi")
                    self.text.append(f"    mov ${self.sizeof(ty_l)}, %rdx")
                    self.text.append("    call memcpy@PLT")
                return ty_l
            
            ty_r = self.gen_expr(right)
            fsz = self.sizeof(ty_l)
            if ty_l.startswith('float'):
                if ty_l == 'float<32>':
                    self.text.append(f"    movss %xmm0, {addr}")
                else:
                    self.text.append(f"    movsd %xmm0, {addr}")
            else:
                if fsz == 1:
                    self.text.append(f"    mov %al, {addr}")
                elif fsz == 2:
                    self.text.append(f"    mov %ax, {addr}")
                elif fsz == 4:
                    self.text.append(f"    mov %eax, {addr}")
                else:
                    self.text.append(f"    mov %rax, {addr}")
            return ty_r
        elif node[0] == 'binop':
            op = node[1]
            left = node[2]
            right = node[3]
            
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
            
            if ty_l.startswith('float'):
                if ty_l == 'float<32>':
                    self.text.append("    movss (%rsp), %xmm1")
                    self.text.append("    add $8, %rsp")
                    if op == '+':
                        self.text.append("    addss %xmm1, %xmm0")
                    elif op == '-':
                        self.text.append("    subss %xmm1, %xmm0")
                else:
                    self.text.append("    movsd (%rsp), %xmm1")
                    self.text.append("    add $8, %rsp")
                    if op == '+':
                        self.text.append("    addsd %xmm1, %xmm0")
                    elif op == '-':
                        self.text.append("    subsd %xmm1, %xmm0")
                return ty_l
            else:
                self.text.append("    pop %rcx") # rcx is the right operand (pushed earlier)
                
                # Apply scaling for pointer arithmetic
                if ptr_scaling > 1:
                    if is_ptr_sub:
                        # (ptr2 - ptr1) / scaling
                        # RAX is ptr1 (left), RCX is ptr2 (right) 
                        # Wait, gen_expr(right) then push rax -> RCX is right. gen_expr(left) -> RAX is left.
                        # so op is RAX op RCX.
                        self.text.append(f"    sub %rcx, %rax")
                        self.text.append("    cqo")
                        self.text.append(f"    mov ${ptr_scaling}, %rcx")
                        self.text.append("    idiv %rcx")
                        return "int"
                    else:
                        # ptr + (int * scaling) or (int * scaling) + ptr
                        if ty_l.endswith('*'):
                            # RAX is ptr, RCX is int
                            self.text.append(f"    imul ${ptr_scaling}, %rcx")
                        else:
                            # RAX is int, RCX is ptr
                            self.text.append(f"    imul ${ptr_scaling}, %rax")

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
                    self.text.append("    mov %rdx, %rax")  # Remainder is in RDX
                elif op == '>':
                    self.text.append("    cmp %rcx, %rax")
                    self.text.append("    setg %al")
                    self.text.append("    movzbq %al, %rax")
                elif op == '<':
                    self.text.append("    cmp %rcx, %rax")
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
                    self.text.append("    setge %al")
                    self.text.append("    movzbq %al, %rax")
                elif op == '<=':
                    self.text.append("    cmp %rcx, %rax")
                    self.text.append("    setle %al")
                    self.text.append("    movzbq %al, %rax")
                return ty_l
        elif node[0] == 'call':
            target = node[1]
            args = node[2]
            
            # Handle method calls on arrays: arr.push(), arr.pop(), arr.length(), arr.clear()
            if target[0] == 'member_access':
                method = target[2]
                base = target[1]
                base_addr, base_ty = self.get_lvalue(base)
                if base_ty.startswith('array<'):
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
                        is_struct = elem_ty in self.structs
                        
                        if is_struct:
                            # For structs, get the source address and use memcpy
                            if args[0][0] == 'init_list':
                                # Struct initializer: create temp struct on stack, then copy
                                st = self.structs[elem_ty]
                                st_sz = self.sizeof(elem_ty)
                                # Allocate temp space on stack
                                self.text.append(f"    sub ${st_sz}, %rsp")
                                temp_off = 0  # offset from rsp
                                field_list = list(st['fields'].items())
                                for fi, fval in enumerate(args[0][1]):
                                    fname, finfo = field_list[fi]
                                    self.gen_expr(fval)
                                    foff = temp_off + finfo['offset']
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
                                # Save src addr on stack (will be restored after potential realloc)
                                self.text.append("    mov %rsp, %r11")
                                self.text.append("    push %r11")  # save src addr
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
                        self.text.append(f"    mov {arr_ref(0)}, %rsi")     # old data ptr (2nd arg for realloc)
                        self.text.append("    xchg %rdi, %rsi")  # rdi=old_ptr, rsi=new_size
                        self.text.append("    mov %rsi, %rsi")   # clear upper bits
                        self.text.append("    xchg %rdi, %rsi")  # rdi=size, rsi=old_ptr -> wrong, fix:
                        # Actually realloc(ptr, size): rdi=ptr, rsi=size
                        self.text.pop(); self.text.pop(); self.text.pop(); self.text.pop()
                        self.text.append(f"    mov {arr_ref(0)}, %rdi")     # old ptr
                        self.text.append(f"    mov {arr_ref(16)}, %rsi")  # new cap
                        self.text.append(f"    imul ${elem_sz}, %rsi")
                        self.text.append("    call realloc@PLT")
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
                            self.text.append("    call memcpy@PLT")
                            if args[0][0] == 'init_list':
                                # Restore stack after temp struct
                                st_sz = self.sizeof(elem_ty)
                                self.text.append(f"    add ${st_sz}, %rsp")
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
                        is_struct = elem_ty in self.structs
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
            if ret_ty in self.structs:
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
                        if arg[0] == 'id' and arg[1] in self.local_vars:
                            var_info = self.local_vars[arg[1]]
                            aoff = var_info[0]
                            aty = var_info[1]
                            self.text.append(f"    pushq {aoff+16}(%rbp)")  # cap (popped last)
                            self.text.append(f"    pushq {aoff+8}(%rbp)")   # len (popped 2nd)
                            self.text.append(f"    pushq {aoff}(%rbp)")     # ptr (popped 1st)
                        else:
                            self.text.append("    push %rax")
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
            reg_offset = 1 if ret_ty in self.structs else 0
            
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

            # For struct returns, load hidden pointer into %rdi
            if ret_ty in self.structs:
                self.text.append(f"    mov %rsp, %rdi")  # Hidden pointer in %rdi

            if is_vararg:
                float_count = len([ty for ty in arg_types if ty.startswith('float')])
                self.text.append(f"    mov ${float_count}, %eax")
            
            if is_func_ptr_call:
                # Load function pointer from variable and call through it
                offset = self.local_vars[func_name][0]
                self.text.append(f"    mov {offset}(%rbp), %r11")
                self.text.append("    call *%r11")
            else:
                self.text.append(f"    call {func_name}@PLT")
            
            # For struct returns, the result is in the hidden pointer location
            # Return pointer to the struct in rax
            if ret_ty in self.structs:
                st_sz = self.sizeof(ret_ty)
                # Align to 16 bytes
                if st_sz % 16 != 0:
                    st_sz += 16 - (st_sz % 16)
                self.text.append("    mov %rsp, %rax")  # Return pointer to struct on stack
                return ret_ty + '*'  # Return as pointer type
            
            return ret_ty
