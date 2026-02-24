class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def consume(self, expected_type=None):
        tok = self.tokens[self.pos]
        if expected_type and tok.type != expected_type:
            raise SyntaxError(f"Expected {expected_type}, got {tok.type} at line {tok.line}")
        self.pos += 1
        return tok

    def _loc(self):
        """Get current location (line, column) from current token."""
        tok = self.peek()
        return (tok.line, tok.column)

    def parse_program(self):
        decls = []
        while self.peek().type != 'EOF':
            if self.peek().type == 'INCLUDE':
                decls.append(self.parse_include())
            elif self.peek().type == 'STRUCT':
                decls.append(self.parse_struct_decl())
            elif self.peek().type == 'ENUM':
                decls.append(self.parse_enum_decl())
            elif self.peek().type == 'LET':
                decls.append(self.parse_let_decl())
            elif self.peek().type == 'MACRO':
                decls.append(self.parse_macro())
            else:
                decls.append(self.parse_decl())
        return decls

    def parse_let_decl(self):
        loc = self._loc()
        self.consume('LET')
        ty = self.parse_type()
        name = self.consume('ID').value
        self.consume('ASSIGN')
        init = self.parse_expr()
        self.consume('SEMI')
        return ('pub_var', ty, name, init, loc)

    def parse_struct_decl(self):
        loc = self._loc()
        self.consume('STRUCT')
        name = self.consume('ID').value
        self.consume('LBRACE')
        fields = []
        while self.peek().type != 'RBRACE':
            fty = self.parse_type()
            fname = self.consume('ID').value
            self.consume('SEMI')
            fields.append((fty, fname))
        self.consume('RBRACE')
        self.consume('SEMI')
        return ('struct_decl', name, fields, loc)

    def parse_enum_decl(self):
        loc = self._loc()
        self.consume('ENUM')
        name = self.consume('ID').value
        self.consume('LBRACE')
        variants = []
        if self.peek().type != 'RBRACE':
            while True:
                variants.append(self.consume('ID').value)
                if self.peek().type == 'COMMA':
                    self.consume('COMMA')
                else:
                    break
        self.consume('RBRACE')
        self.consume('SEMI')
        return ('enum_decl', name, variants, loc)

    def parse_macro(self):
        loc = self._loc()
        self.consume('MACRO')
        name = self.consume('ID').value
        self.consume('LPAREN')
        params = []
        if self.peek().type != 'RPAREN':
            while True:
                params.append(self.consume('ID').value)
                if self.peek().type == 'COMMA':
                    self.consume('COMMA')
                else:
                    break
        self.consume('RPAREN')
        self.consume('LBRACE')
        # Parse macro body - can be either statements or a single expression
        body = []
        while self.peek().type != 'RBRACE':
            # Try to parse as statement first, but allow expressions without semicolons
            if self.peek().type in ('IF', 'WHILE', 'FOR', 'DO', 'RETURN', 'VOID', 'SIGNED', 'UNSIGNED') or \
               (self.peek().type == 'ID' and self._is_decl_start()):
                body.append(self.parse_stmt())
            else:
                # Parse as expression
                expr = self.parse_expr()
                if self.peek().type == 'SEMI':
                    self.consume('SEMI')
                    body.append(('expr_stmt', expr, loc))
                else:
                    # Expression without semicolon - store as-is
                    body.append(('expr_stmt', expr, loc))
        self.consume('RBRACE')
        return ('macro', name, params, body, loc)
    
    def _is_decl_start(self):
        """Check if current position starts a declaration (for macro parsing)."""
        pos = self.pos
        if self.peek().type != 'ID':
            return False
        # Skip base type ID
        look = pos + 1
        # Skip <...>
        if look < len(self.tokens) and self.tokens[look].type == 'LT':
            nest = 1
            look += 1
            while look < len(self.tokens) and nest > 0:
                if self.tokens[look].type == 'LT': nest += 1
                if self.tokens[look].type == 'GT': nest -= 1
                look += 1
        # Skip *
        while look < len(self.tokens) and self.tokens[look].type == 'MUL':
            look += 1
        # If next is an ID, it's a declaration
        return look < len(self.tokens) and self.tokens[look].type == 'ID'

    def parse_include(self):
        self.consume('INCLUDE')
        self.consume('LT')
        fname = self.consume('ID').value
        if self.peek().type == 'DOT':
            self.consume('DOT')
            fname += '.' + self.consume('ID').value
        self.consume('GT')
        return ('include', fname)

    def parse_type(self):
        # Handle signed/unsigned modifiers
        sign_modifier = None
        if self.peek().type == 'SIGNED':
            self.consume('SIGNED')
            sign_modifier = 'signed'
        elif self.peek().type == 'UNSIGNED':
            self.consume('UNSIGNED')
            sign_modifier = 'unsigned'
        
        if self.peek().type == 'VOID':
            self.consume('VOID')
            base = 'void'
        else:
            base = self.consume('ID').value
            if self.peek().type == 'LT':
                self.consume('LT')
                if self.peek().type == 'NUMBER':
                    size = self.consume('NUMBER').value
                    self.consume('GT')
                    base = f"{base}<{size}>"
                else:
                    inner_ty = self.parse_type()
                    self.consume('GT')
                    base = f"{base}<{inner_ty}>"
        
        # Apply sign modifier to the type
        if sign_modifier:
            base = f"{sign_modifier} {base}"
        
        while self.peek().type == 'MUL':
            self.consume('MUL')
            base += '*'
        return base
            
    def parse_decl(self):
        loc = self._loc()
        ty = self.parse_type()
        name = self.consume('ID').value
        self.consume('LPAREN')
        params = []
        varargs = False
        if self.peek().type != 'RPAREN':
            while True:
                if self.peek().type == 'ELLIPSIS':
                    self.consume('ELLIPSIS')
                    varargs = True
                    break
                pty = self.parse_type()
                pname = self.consume('ID').value
                params.append((pty, pname))
                if self.peek().type == 'COMMA':
                    self.consume('COMMA')
                else:
                    break
        self.consume('RPAREN')
        if self.peek().type == 'SEMI':
            self.consume('SEMI')
            return ('extern', ty, name, params, varargs, loc)
        elif self.peek().type == 'LBRACE':
            self.consume('LBRACE')
            body = []
            while self.peek().type != 'RBRACE':
                body.append(self.parse_stmt())
            self.consume('RBRACE')
            return ('func', ty, name, params, body, loc)
        else:
            raise SyntaxError(f"Unexpected {self.peek().type} after function signature on line {self.peek().line}")

    def parse_if_stmt(self):
        loc = self._loc()
        self.consume('IF')
        self.consume('LPAREN')
        cond = self.parse_expr()
        self.consume('RPAREN')
        self.consume('LBRACE')
        body = []
        while self.peek().type != 'RBRACE':
            body.append(self.parse_stmt())
        self.consume('RBRACE')
        
        else_body = None
        if self.peek().type == 'ELSE':
            self.consume('ELSE')
            if self.peek().type == 'IF':
                else_body = [self.parse_if_stmt()]
            else:
                self.consume('LBRACE')
                else_body = []
                while self.peek().type != 'RBRACE':
                    else_body.append(self.parse_stmt())
                self.consume('RBRACE')
        return ('if_stmt', cond, body, else_body, loc)

    def parse_while_stmt(self):
        loc = self._loc()
        self.consume('WHILE')
        self.consume('LPAREN')
        cond = self.parse_expr()
        self.consume('RPAREN')
        self.consume('LBRACE')
        body = []
        while self.peek().type != 'RBRACE':
            body.append(self.parse_stmt())
        self.consume('RBRACE')
        return ('while_stmt', cond, body, loc)

    def parse_do_while_stmt(self):
        loc = self._loc()
        self.consume('DO')
        self.consume('LBRACE')
        body = []
        while self.peek().type != 'RBRACE':
            body.append(self.parse_stmt())
        self.consume('RBRACE')
        self.consume('WHILE')
        self.consume('LPAREN')
        cond = self.parse_expr()
        self.consume('RPAREN')
        self.consume('SEMI')
        return ('do_while_stmt', body, cond, loc)

    def parse_for_stmt(self):
        loc = self._loc()
        self.consume('FOR')
        self.consume('LPAREN')
        init = self.parse_stmt()
        cond = self.parse_expr()
        self.consume('SEMI')
        inc = self.parse_expr()
        self.consume('RPAREN')
        self.consume('LBRACE')
        body = []
        while self.peek().type != 'RBRACE':
            body.append(self.parse_stmt())
        self.consume('RBRACE')
        return ('for_stmt', init, cond, inc, body, loc)

    def parse_stmt(self):
        if self.peek().type == 'IF':
            return self.parse_if_stmt()
        if self.peek().type == 'WHILE':
            return self.parse_while_stmt()
        if self.peek().type == 'FOR':
            return self.parse_for_stmt()
        if self.peek().type == 'DO':
            return self.parse_do_while_stmt()
        
        loc = self._loc()
        is_decl = False
        pos = self.pos
        # Check for signed/unsigned modifiers
        if self.peek().type in ('SIGNED', 'UNSIGNED'):
            is_decl = True
        elif self.peek().type == 'ID':
            # Skip base type ID
            look = pos + 1
            # Skip <...>
            if look < len(self.tokens) and self.tokens[look].type == 'LT':
                nest = 1
                look += 1
                while look < len(self.tokens) and nest > 0:
                    if self.tokens[look].type == 'LT': nest += 1
                    if self.tokens[look].type == 'GT': nest -= 1
                    look += 1
            # Skip *
            while look < len(self.tokens) and self.tokens[look].type == 'MUL':
                look += 1
            
            # If next is an ID, it's a declaration
            if look < len(self.tokens) and self.tokens[look].type == 'ID':
                is_decl = True
        elif self.peek().type == 'VOID':
            is_decl = True
        
        if is_decl:
            ty = self.parse_type()
            name = self.consume('ID').value
            if self.peek().type == 'SEMI':
                self.consume('SEMI')
                return ('var_decl', ty, name, None, loc)
            self.consume('ASSIGN')
            if self.peek().type == 'LBRACE':
                self.consume('LBRACE')
                init_list = []
                if self.peek().type != 'RBRACE':
                    while True:
                        init_list.append(self.parse_expr())
                        if self.peek().type == 'COMMA':
                            self.consume('COMMA')
                        else:
                            break
                self.consume('RBRACE')
                init_expr = ('init_list', init_list)
            else:
                init_expr = self.parse_expr()
            self.consume('SEMI')
            return ('var_decl', ty, name, init_expr, loc)
            
        if self.peek().type == 'RETURN':
            self.consume('RETURN')
            if self.peek().type != 'SEMI':
                expr = self.parse_expr()
                self.consume('SEMI')
                return ('return_stmt', expr, loc)
            self.consume('SEMI')
            return ('return_stmt', None, loc)
            
        expr = self.parse_expr()
        self.consume('SEMI')
        return ('expr_stmt', expr, loc)

    def parse_expr(self):
        loc = self._loc()
        left = self.parse_comparison()
        if self.peek().type == 'ASSIGN':
            self.consume('ASSIGN')
            right = self.parse_expr()
            return ('assign', left, right, loc)
        return left

    def parse_comparison(self):
        loc = self._loc()
        left = self.parse_arithmetic()
        while self.peek().type in ('GT', 'LT', 'EQ', 'NEQ', 'LEQ', 'GEQ'):
            op = self.consume().value
            right = self.parse_arithmetic()
            left = ('binop', op, left, right, loc)
        return left

    def parse_arithmetic(self):
        loc = self._loc()
        left = self.parse_factor()
        while self.peek().type in ('PLUS', 'MINUS'):
            op = self.consume().value
            right = self.parse_factor()
            left = ('binop', op, left, right, loc)
        return left

    def parse_factor(self):
        loc = self._loc()
        left = self.parse_unary()
        while self.peek().type in ('MUL', 'DIV', 'MOD'):
            op = self.consume().value
            right = self.parse_unary()
            left = ('binop', op, left, right, loc)
        return left

    def parse_unary(self):
        loc = self._loc()
        if self.peek().type in ('MUL', 'AMP', 'PLUS', 'MINUS'):
            op = self.consume().value
            target = self.parse_unary()
            return ('unary', op, target, loc)
        return self.parse_primary()

    def parse_primary(self):
        loc = self._loc()
        if self.peek().type == 'LPAREN':
            self.consume('LPAREN')
            target = self.parse_expr()
            self.consume('RPAREN')
        elif self.peek().type == 'FLOAT':
            target = ('float', float(self.consume('FLOAT').value), loc)
        elif self.peek().type == 'NUMBER':
            target = ('number', int(self.consume('NUMBER').value), loc)
        elif self.peek().type == 'CHAR':
            target = ('char', self.consume('CHAR').value, loc)
        elif self.peek().type == 'STRING':
            target = ('string', self.consume('STRING').value, loc)
        elif self.peek().type == 'ID':
            base = self.consume('ID').value
            if self.peek().type == 'COLONCOLON':
                self.consume('COLONCOLON')
                name = self.consume('ID').value
                target = ('namespace_access', base, name, loc)
            else:
                target = ('id', base, loc)
        elif self.peek().type == 'LBRACE':
            self.consume('LBRACE')
            items = []
            if self.peek().type != 'RBRACE':
                while True:
                    items.append(self.parse_expr())
                    if self.peek().type == 'COMMA':
                        self.consume('COMMA')
                    else:
                        break
            self.consume('RBRACE')
            target = ('init_list', items, loc)
        else:
            raise SyntaxError(f"Unexpected token {self.peek().type} in expression at line {self.peek().line}")

        while True:
            if self.peek().type == 'DOT':
                self.consume('DOT')
                field = self.consume('ID').value
                target = ('member_access', target, field, loc)
            elif self.peek().type == 'ARROW':
                self.consume('ARROW')
                field = self.consume('ID').value
                target = ('arrow_access', target, field, loc)
            elif self.peek().type == 'LBRACKET':
                self.consume('LBRACKET')
                idx = self.parse_expr()
                self.consume('RBRACKET')
                target = ('array_access', target, idx, loc)
            elif self.peek().type == 'LPAREN':
                self.consume('LPAREN')
                args = []
                if self.peek().type != 'RPAREN':
                    while True:
                        args.append(self.parse_expr())
                        if self.peek().type == 'COMMA':
                            self.consume('COMMA')
                        else:
                            break
                self.consume('RPAREN')
                target = ('call', target, args, loc)
            else:
                break
        return target
