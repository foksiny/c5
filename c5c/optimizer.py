class Optimizer:
    def optimize_ast(self, ast):
        return self._opt_ast(ast)
        
    def _is_safe(self, ast):
        """Check if an AST node has no side effects."""
        if not ast: return True
        if isinstance(ast, list):
            return all(self._is_safe(n) for n in ast)
        if isinstance(ast, tuple):
            tag = ast[0]
            if tag in ('number', 'float', 'string', 'char', 'id'): return True
            if tag == 'binop': return self._is_safe(ast[2]) and self._is_safe(ast[3])
            if tag == 'unary': return self._is_safe(ast[2])
            # Array access might be safe if index is safe, but let's be conservative
            if tag == 'array_access': return self._is_safe(ast[1]) and self._is_safe(ast[2])
            # Function calls, assignments, etc are NOT safe
            return False
        return True

    def _opt_ast(self, ast):
        if not ast: return ast

        # Handle list of statements (e.g., block bodies)
        if isinstance(ast, list):
            new_list = []
            for node in ast:
                res = self._opt_ast(node)
                if isinstance(res, list):
                    new_list.extend(res)
                elif res is not None:
                    new_list.append(res)
            return new_list

        if isinstance(ast, tuple):
            tag = ast[0]
            
            # --- Binary Operations ---
            if tag == 'binop':
                op = ast[1]
                left = self._opt_ast(ast[2])
                right = self._opt_ast(ast[3])
                
                # Constant Folding
                if left and left[0] == 'number' and right and right[0] == 'number':
                    try:
                        lval = int(left[1])
                        rval = int(right[1])
                        if op == '+': return ('number', str(lval + rval)) + ast[4:]
                        if op == '-': return ('number', str(lval - rval)) + ast[4:]
                        if op == '*': return ('number', str(lval * rval)) + ast[4:]
                        if op == '/': return ('number', str(lval // rval)) + ast[4:]
                        if op == '%': return ('number', str(lval % rval)) + ast[4:]
                        if op == '>': return ('number', '1' if lval > rval else '0') + ast[4:]
                        if op == '<': return ('number', '1' if lval < rval else '0') + ast[4:]
                        if op == '==': return ('number', '1' if lval == rval else '0') + ast[4:]
                        if op == '!=': return ('number', '1' if lval != rval else '0') + ast[4:]
                        if op == '>=': return ('number', '1' if lval >= rval else '0') + ast[4:]
                        if op == '<=': return ('number', '1' if lval <= rval else '0') + ast[4:]
                        if op == '&': return ('number', str(lval & rval)) + ast[4:]
                        if op == '|': return ('number', str(lval | rval)) + ast[4:]
                        if op == '^': return ('number', str(lval ^ rval)) + ast[4:]
                        if op == '<<': return ('number', str(lval << rval)) + ast[4:]
                        if op == '>>': return ('number', str(lval >> rval)) + ast[4:]
                        if op == '&&': return ('number', '1' if lval and rval else '0') + ast[4:]
                        if op == '||': return ('number', '1' if lval or rval else '0') + ast[4:]
                    except Exception:
                        pass
                
                # Identity Operations
                # Check right operand
                if right and right[0] == 'number':
                    try:
                        rval = int(right[1])
                        if op == '+' and rval == 0: return left
                        if op == '-' and rval == 0: return left
                        if op == '*' and rval == 1: return left
                        if op == '/' and rval == 1: return left
                        if op == '*' and rval == 0:
                            if self._is_safe(left): return ('number', '0') + ast[4:]
                    except: pass
                
                # Check left operand
                if left and left[0] == 'number':
                    try:
                        lval = int(left[1])
                        if op == '+' and lval == 0: return right
                        if op == '*' and lval == 1: return right
                        if op == '*' and lval == 0:
                             if self._is_safe(right): return ('number', '0') + ast[4:]
                    except: pass

                # Reconstruct node
                return ('binop', op, left, right) + ast[4:]

            # --- Unary Operations ---
            if tag == 'unary':
                op = ast[1]
                target = self._opt_ast(ast[2])
                
                if target and target[0] == 'number':
                    try:
                        val = int(target[1])
                        if op == '-': return ('number', str(-val)) + ast[3:]
                        if op == '+': return target
                        if op == '~': return ('number', str(~val)) + ast[3:]
                        if op == '!': return ('number', '1' if val == 0 else '0') + ast[3:]
                    except: pass
                
                return ('unary', op, target) + ast[3:]

            # --- If Statement ---
            if tag == 'if_stmt':
                # ('if_stmt', cond, body, else_body, loc)
                cond = self._opt_ast(ast[1])
                body = self._opt_ast(ast[2])
                else_body = self._opt_ast(ast[3]) if ast[3] else None
                
                if cond and cond[0] == 'number':
                    try:
                        val = int(cond[1])
                        if val != 0:
                            # True: return body
                            return body
                        else:
                            # False: return else_body
                            return else_body if else_body else [] 
                    except: pass
                
                return ('if_stmt', cond, body, else_body) + ast[4:]

            # --- While Statement ---
            if tag == 'while_stmt':
                # ('while_stmt', cond, body, loc)
                cond = self._opt_ast(ast[1])
                body = self._opt_ast(ast[2])
                
                if cond and cond[0] == 'number':
                    try:
                        val = int(cond[1])
                        if val == 0:
                            # While(0) -> Remove loop
                            return []
                    except: pass
                
                return ('while_stmt', cond, body) + ast[3:]

            # --- Generic Recursion ---
            # Optimistically recurse into all tuple elements that look like AST nodes or lists
            new_ast = list(ast)
            changed = False
            for i in range(1, len(ast)):
                item = ast[i]
                if isinstance(item, (tuple, list)):
                    new_item = self._opt_ast(item)
                    if new_item is not item:
                        new_ast[i] = new_item
                        changed = True
            
            if changed:
                return tuple(new_ast)
            
        return ast
        
    def optimize_asm(self, asm_lines):
        # First pass: Build label map to optimize jumps
        label_map = {}
        for i, line in enumerate(asm_lines):
            s = line.strip()
            if s.endswith(':'):
                label = s[:-1]
                label_map[label] = i

        changed = True
        pass_count = 0
        while changed and pass_count < 10: # Limit passes to avoid infinite loops
            changed = False
            pass_count += 1
            new_asm = []
            i = 0
            while i < len(asm_lines):
                line = asm_lines[i]
                s = line.strip()
                
                # Peek next line
                next_line = asm_lines[i+1] if i + 1 < len(asm_lines) else ""
                next_s = next_line.strip()
                
                # --- Jump Optimizations ---
                
                # 1. Jump to next line
                # jmp L1 \n L1: ... -> remove jmp
                if s.startswith('jmp '):
                    target = s[4:]
                    if next_s == target + ':':
                        i += 1 # Skip jmp
                        changed = True
                        continue

                # --- Instruction Redundancy ---

                # 2. Push/Pop Identity
                # push A \n pop A -> remove
                if s.startswith('push ') and next_s.startswith('pop '):
                    a = s[5:]
                    b = next_s[4:]
                    if a == b:
                        i += 2
                        changed = True
                        continue
                    else:
                        # push A \n pop B -> mov A, B
                        # Safety check: if operands are memory references (contain '('), be careful.
                        if '(' in a and '(' in b:
                             # Can't optimize to single mov
                             pass 
                        else:
                            lead = line[:line.index('p')]
                            new_asm.append(f"{lead}mov {a}, {b}")
                            i += 2
                            changed = True
                            continue
                            
                # 3. Redundant Moves
                # mov A, B \n mov B, A -> mov A, B
                if s.startswith('mov ') and next_s.startswith('mov '):
                    p1 = s[4:].split(', ')
                    p2 = next_s[4:].split(', ')
                    if len(p1) == 2 and len(p2) == 2:
                        if p1[0] == p2[1] and p1[1] == p2[0]:
                            new_asm.append(line)
                            i += 2
                            changed = True
                            continue
                
                # 4. Self Move
                # mov A, A -> remove
                if s.startswith('mov '):
                    p1 = s[4:].split(', ')
                    if len(p1) == 2 and p1[0] == p1[1]:
                        i += 1
                        changed = True
                        continue

                # --- Arithmetic Identities & Strength Reduction ---
                
                # 5. Add 0 -> remove
                if s.startswith('add $0,'):
                    i += 1
                    changed = True
                    continue
                    
                # 6. Sub 0 -> remove
                if s.startswith('sub $0,'):
                    i += 1
                    changed = True
                    continue

                # 7. Mul 1 -> remove
                if s.startswith('imul $1,'):
                    i += 1
                    changed = True
                    continue

                # 8. Add 1 -> Inc
                if s.startswith('add $1, '):
                    parts = s[8:]
                    lead = line[:line.index('a')]
                    new_asm.append(f"{lead}inc {parts}")
                    i += 1
                    changed = True
                    continue

                # 9. Sub 1 -> Dec
                if s.startswith('sub $1, '):
                    parts = s[8:]
                    lead = line[:line.index('s')]
                    new_asm.append(f"{lead}dec {parts}")
                    i += 1
                    changed = True
                    continue

                # 10. Mul Power of 2 -> Shift
                # imul $2, %reg -> shl $1, %reg
                if s.startswith('imul $'):
                    # Parse: imul $N, %reg
                    try:
                        rest = s[6:]
                        val_str, reg = rest.split(', ')
                        val = int(val_str)
                        if val == 2:
                            lead = line[:line.index('i')]
                            new_asm.append(f"{lead}shl $1, {reg}")
                            i += 1
                            changed = True
                            continue
                        elif val == 4:
                            lead = line[:line.index('i')]
                            new_asm.append(f"{lead}shl $2, {reg}")
                            i += 1
                            changed = True
                            continue
                        elif val == 8:
                            lead = line[:line.index('i')]
                            new_asm.append(f"{lead}shl $3, {reg}")
                            i += 1
                            changed = True
                            continue
                        elif val == 16:
                            lead = line[:line.index('i')]
                            new_asm.append(f"{lead}shl $4, {reg}")
                            i += 1
                            changed = True
                            continue
                    except:
                        pass

                # 11. Cmp 0 -> Test
                # cmp $0, %reg -> test %reg, %reg
                if s.startswith('cmp $0, '):
                    reg = s[8:]
                    if not reg.startswith('$') and '(' not in reg: # Register only
                        lead = line[:line.index('c')]
                        new_asm.append(f"{lead}test {reg}, {reg}")
                        i += 1
                        changed = True
                        continue

                # --- 3-Instruction Windows ---
                if i + 2 < len(asm_lines):
                    s3 = asm_lines[i+2].strip()

                    # 12. Push-Mov-Pop pattern
                    # push A \n mov X, B \n pop C
                    if s.startswith('push ') and next_s.startswith('mov ') and s3.startswith('pop '):
                        a = s[5:]
                        c = s3[4:]
                        parts = next_s[4:].split(', ')
                        if len(parts) == 2:
                            b_dest = parts[1]
                            b_src = parts[0]
                            if b_dest != a and b_dest != c and b_src != c:
                                lead = line[:line.index('p')]
                                if a != c:
                                    new_asm.append(f"{lead}mov {a}, {c}")
                                new_asm.append(asm_lines[i+1])
                                i += 3
                                changed = True
                                continue

                new_asm.append(line)
                i += 1
            asm_lines = new_asm
            
        return asm_lines
