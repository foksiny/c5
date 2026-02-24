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
        self.local_vars = {}
        self.local_var_offset = 0
        self.label_count = 0
        self.global_vars = {}
        self.data = []
        self.uses_str_add = False
        self.uses_str_sub = False

    def sizeof(self, ty):
        if ty.endswith('*'): return 8
        if ty.startswith('array<'): return 24  # ptr + len + cap
        # Handle signed/unsigned types
        if ty.startswith('unsigned ') or ty.startswith('signed '):
            ty = ty.split(' ', 1)[1]  # Strip the modifier for size calculation
        if ty == 'int<8>' or ty == 'char': return 1
        if ty == 'int<16>': return 2
        if ty == 'int<32>' or ty == 'float<32>': return 4
        if ty == 'int' or ty == 'float' or ty == 'float<64>' or ty == 'string': return 8
        if ty in self.structs: return self.structs[ty]['size']
        if ty in self.enums: return 4
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
                offset, ty = self.local_vars[node[1]]
                return f"{offset}(%rbp)", ty
            if node[1] in self.global_vars:
                ty = self.global_vars[node[1]]
                return f"{node[1]}(%rip)", ty
            raise Exception(f"Unknown var {node[1]}")
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
                self.data.append(f".global {name}")
                self.data.append(f"{name}:")
                if init[0] == 'number':
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
            
        if name == "main":
            self.text.append("    mov $0, %eax")

        self.text.append("    leave")
        self.text.append("    ret")

    def gen_stmt(self, node):
        if node[0] == 'expr_stmt':
            self.gen_expr(node[1])
        elif node[0] == 'var_decl':
            _, ty, name, init_expr = node
            sz = self.sizeof(ty)
            align = sz if sz < 8 else 8
            align = 8 if align == 8 else align
            if abs(self.local_var_offset) % align != 0:
                self.local_var_offset -= align - (abs(self.local_var_offset) % align)
            self.local_var_offset -= sz
            self.local_vars[name] = (self.local_var_offset, ty)
            
            # Zero-initialize arrays when declared without initializer
            if ty.startswith('array<') and not init_expr:
                base_off = self.local_var_offset
                self.text.append(f"    movq $0, {base_off}(%rbp)")       # data ptr = NULL
                self.text.append(f"    movq $0, {base_off+8}(%rbp)")     # length = 0
                self.text.append(f"    movq $0, {base_off+16}(%rbp)")    # capacity = 0
            
            if init_expr:
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
                    if ty.startswith('float'):
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
            if node[1]:
                ret_expr = node[1]
                # Check if we're returning an array variable
                if ret_expr[0] == 'id' and ret_expr[1] in self.local_vars:
                    off, vty = self.local_vars[ret_expr[1]]
                    if vty.startswith('array<'):
                        self.text.append(f"    mov {off}(%rbp), %rax")       # data ptr
                        self.text.append(f"    mov {off+8}(%rbp), %rdx")     # length
                        self.text.append(f"    mov {off+16}(%rbp), %rcx")    # capacity
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
            for stmt in body:
                self.gen_stmt(stmt)
            self.text.append(f"    jmp {cond_label}")
            self.text.append(f"{end_label}:")
        elif node[0] == 'do_while_stmt':
            body, cond = node[1], node[2]
            self.label_count += 1
            start_label = f".Ldo_start_{self.label_count}"
            self.text.append(f"{start_label}:")
            for stmt in body:
                self.gen_stmt(stmt)
            self.gen_expr(cond)
            self.text.append("    cmp $0, %rax")
            self.text.append(f"    jne {start_label}")
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
            for stmt in body:
                self.gen_stmt(stmt)
            self.gen_expr(inc)
            self.text.append(f"    jmp {cond_label}")
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
            if base in self.enums and name in self.enums[base]:
                val = self.enums[base][name]
                self.text.append(f"    mov ${val}, %rax")
                return "int"
            else:
                raise Exception(f"Unknown namespace access: {base}::{name}")
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

            ty_r = self.gen_expr(right)
            addr, ty_l = self.get_lvalue(left)
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
                    if '(%rbp)' in base_addr:
                        base_off = int(base_addr.split('(')[0])
                    else:
                        raise Exception("Arrays must be local variables")
                    
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
                        self.text.append(f"    mov {base_off+8}(%rbp), %r10")   # len
                        self.text.append(f"    cmp {base_off+16}(%rbp), %r10")  # cmp len, cap
                        self.text.append(f"    jl {skip_grow}")
                        # Grow: new_cap = cap * 2 (or 4 if 0)
                        self.text.append(f"    mov {base_off+16}(%rbp), %rdi")
                        self.text.append("    shl $1, %rdi")
                        self.text.append("    cmp $4, %rdi")
                        self.label_count += 1
                        cap_ok = f".Lcap_ok_{self.label_count}"
                        self.text.append(f"    jge {cap_ok}")
                        self.text.append("    mov $4, %rdi")
                        self.text.append(f"{cap_ok}:")
                        self.text.append(f"    mov %rdi, {base_off+16}(%rbp)")  # update cap
                        self.text.append(f"    imul ${elem_sz}, %rdi")
                        self.text.append(f"    mov {base_off}(%rbp), %rsi")     # old data ptr (2nd arg for realloc)
                        self.text.append("    xchg %rdi, %rsi")  # rdi=old_ptr, rsi=new_size
                        self.text.append("    mov %rsi, %rsi")   # clear upper bits
                        self.text.append("    xchg %rdi, %rsi")  # rdi=size, rsi=old_ptr -> wrong, fix:
                        # Actually realloc(ptr, size): rdi=ptr, rsi=size
                        self.text.pop(); self.text.pop(); self.text.pop(); self.text.pop()
                        self.text.append(f"    mov {base_off}(%rbp), %rdi")     # old ptr
                        self.text.append(f"    mov {base_off+16}(%rbp), %rsi")  # new cap
                        self.text.append(f"    imul ${elem_sz}, %rsi")
                        self.text.append("    call realloc@PLT")
                        self.text.append(f"    mov %rax, {base_off}(%rbp)")     # update data ptr
                        self.text.append(f"{skip_grow}:")
                        
                        # Store value at data[len]
                        if is_struct:
                            # Use memcpy to copy struct data
                            self.text.append("    pop %r11")  # restore src addr
                            self.text.append(f"    mov {base_off}(%rbp), %rdi")  # dest = data ptr
                            self.text.append(f"    mov {base_off+8}(%rbp), %r10") # current len
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
                            self.text.append(f"    mov {base_off}(%rbp), %rcx")  # data ptr
                            self.text.append(f"    mov {base_off+8}(%rbp), %r10") # current len
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
                        self.text.append(f"    incq {base_off+8}(%rbp)")
                        return 'void'
                    
                    elif method == 'pop':
                        # Decrement length, return data[new_len]
                        is_struct = elem_ty in self.structs
                        self.text.append(f"    decq {base_off+8}(%rbp)")
                        self.text.append(f"    mov {base_off+8}(%rbp), %r10") # new len
                        self.text.append(f"    mov {base_off}(%rbp), %rcx")   # data ptr
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
                        self.text.append(f"    mov {base_off+8}(%rbp), %rax")
                        return 'int'
                    
                    elif method == 'clear':
                        self.text.append(f"    movq $0, {base_off+8}(%rbp)")
                        return 'void'
                
                raise Exception(f"Unknown method {method} on type {base_ty}")
            
            func_name = ""
            full_func_name = ""
            if target[0] == 'namespace_access':
                full_func_name = f"{target[1]}::{target[2]}"
                func_name = target[2]
            elif target[0] == 'id':
                func_name = target[1]
                full_func_name = func_name
            
            # Check if the function returns an array type
            ret_ty = "int"
            if full_func_name in self.func_signatures:
                ret_ty = self.func_signatures[full_func_name]
            elif func_name in self.func_signatures:
                ret_ty = self.func_signatures[func_name]
            
            is_vararg = False
            if full_func_name in self.extern_funcs and self.extern_funcs[full_func_name]['varargs']:
                is_vararg = True
            elif func_name in self.extern_funcs and self.extern_funcs[func_name]['varargs']:
                is_vararg = True
            
            # For array arguments, pass the 3 fields (ptr, len, cap)
            arg_types = []
            for arg in args:
                if arg[0] == 'init_list':
                    # Inline init_list passed as function arg: create temp array
                    # We need to know the expected type. For now infer from context.
                    # Allocate temp array on stack
                    items = arg[1]
                    count = len(items)
                    # Infer elem type from function signature or first element
                    # For simplicity, assume int<32> if we can't determine
                    # Check function params
                    param_ty = None
                    for fnode in [n for n in self._current_ast if n[0] == 'func' and n[2] == func_name]:
                        params = fnode[3]
                        idx = len(arg_types)
                        if idx < len(params):
                            param_ty = params[idx][0]
                    if param_ty and param_ty.startswith('array<'):
                        a_elem_ty = self.array_elem_type(param_ty)
                    else:
                        a_elem_ty = 'int<32>'
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
                    # Pop order will be: ptr, len, cap (matching rdi, rsi, rdx)
                    # So push order must be: cap, len, ptr
                    self.text.append("    pop %r11")  # data ptr in r11
                    self.text.append(f"    mov ${count}, %rax")
                    self.text.append("    push %rax")    # push cap (will be popped last -> rdx)
                    self.text.append(f"    mov ${count}, %rax")
                    self.text.append("    push %rax")    # push len (will be popped 2nd -> rsi)
                    self.text.append("    push %r11")    # push ptr (will be popped 1st -> rdi)
                    arg_types.append(param_ty if param_ty else f'array<{a_elem_ty}>')
                else:
                    ty = self.gen_expr(arg)
                    if ty.startswith('float'):
                        self.text.append("    sub $8, %rsp")
                        if ty == 'float<32>':
                            self.text.append("    movss %xmm0, (%rsp)")
                        else:
                            self.text.append("    movsd %xmm0, (%rsp)")
                    elif ty.startswith('array<'):
                        # Push array fields in LIFO order: cap, len, ptr
                        if arg[0] == 'id' and arg[1] in self.local_vars:
                            aoff, aty = self.local_vars[arg[1]]
                            self.text.append(f"    pushq {aoff+16}(%rbp)")  # cap (popped last)
                            self.text.append(f"    pushq {aoff+8}(%rbp)")   # len (popped 2nd)
                            self.text.append(f"    pushq {aoff}(%rbp)")     # ptr (popped 1st)
                        else:
                            self.text.append("    push %rax")
                    else:
                        self.text.append("    push %rax")
                    arg_types.append(ty)
                
            int_regs = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
            float_regs = ["%xmm0", "%xmm1", "%xmm2", "%xmm3", "%xmm4", "%xmm5"]
            
            # For arrays, we need 3 int regs per array arg
            # Count how many int regs we need
            int_slots = 0
            float_slots = 0
            for ty in arg_types:
                if ty.startswith('float'):
                    float_slots += 1
                elif ty.startswith('array<'):
                    int_slots += 3  # ptr, len, cap
                else:
                    int_slots += 1
            
            int_idx = int_slots - 1
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
                else:
                    reg = int_regs[int_idx]
                    int_idx -= 1
                    self.text.append(f"    pop {reg}")

            if is_vararg:
                float_count = len([ty for ty in arg_types if ty.startswith('float')])
                self.text.append(f"    mov ${float_count}, %eax")
                
            self.text.append(f"    call {func_name}@PLT")
            
            return ret_ty
