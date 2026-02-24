class Optimizer:
    def optimize_ast(self, ast):
        return self._opt_ast(ast)
        
    def _opt_ast(self, ast):
        if not ast: return ast
        if isinstance(ast, tuple):
            if ast[0] == 'binop':
                op = ast[1]
                left = self._opt_ast(ast[2])
                right = self._opt_ast(ast[3])
                if left and left[0] == 'number' and right and right[0] == 'number':
                    lval = int(left[1])
                    rval = int(right[1])
                    try:
                        if op == '+': return ('number', str(lval + rval))
                        if op == '-': return ('number', str(lval - rval))
                        if op == '*': return ('number', str(lval * rval))
                        if op == '/': return ('number', str(lval // rval))
                        if op == '>': return ('number', '1' if lval > rval else '0')
                        if op == '<': return ('number', '1' if lval < rval else '0')
                        if op == '==': return ('number', '1' if lval == rval else '0')
                        if op == '!=': return ('number', '1' if lval != rval else '0')
                        if op == '>=': return ('number', '1' if lval >= rval else '0')
                        if op == '<=': return ('number', '1' if lval <= rval else '0')
                    except Exception:
                        pass
                return ('binop', op, left, right)

            new_ast = list(ast)
            for i in range(1, len(ast)):
                if isinstance(ast[i], (tuple, list)):
                    new_ast[i] = self._opt_ast(ast[i])
            return tuple(new_ast)
            
        if isinstance(ast, list):
            return [self._opt_ast(node) for node in ast]
            
        return ast
        
    def optimize_asm(self, asm_lines):
        changed = True
        while changed:
            changed = False
            new_asm = []
            i = 0
            while i < len(asm_lines):
                line = asm_lines[i]
                s = line.strip()
                if i + 1 < len(asm_lines):
                    next_s = asm_lines[i+1].strip()
                    
                    # jmp to next line
                    if s.startswith('jmp '):
                        target = s[4:]
                        if next_s == target + ':':
                            i += 1
                            changed = True
                            continue

                    # push A \n pop A -> remove completely
                    if s.startswith('push ') and next_s.startswith('pop '):
                        a = s[5:]
                        b = next_s[4:]
                        if a == b:
                            i += 2
                            changed = True
                            continue
                        else:
                            # push A \n pop B -> mov A, B
                            lead = line[:line.index('p')]
                            new_asm.append(f"{lead}mov {a}, {b}")
                            i += 2
                            changed = True
                            continue
                            
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
                                
                    # add $0, A -> remove
                    if s.startswith('add $0,'):
                        i += 1
                        changed = True
                        continue
                        
                    # sub $0, A -> remove
                    if s.startswith('sub $0,'):
                        i += 1
                        changed = True
                        continue

                    # mov A, A -> remove
                    if s.startswith('mov '):
                        p1 = s[4:].split(', ')
                        if len(p1) == 2 and p1[0] == p1[1]:
                            i += 1
                            changed = True
                            continue

                    # 3-window patterns
                    if i + 2 < len(asm_lines):
                        s3 = asm_lines[i+2].strip()

                        # push A \n mov X, B \n pop C
                        if s.startswith('push ') and next_s.startswith('mov ') and s3.startswith('pop '):
                            a = s[5:]
                            c = s3[4:]
                            parts = next_s.split(', ')
                            b_dest = parts[-1] if len(parts) == 2 else ''
                            
                            # if B dest is not A or C
                            if b_dest and a != b_dest and c != b_dest:
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
