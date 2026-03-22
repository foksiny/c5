class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        # Track known type names for disambiguation (built-in + user-defined)
        self.type_names = {'int', 'char', 'float', 'string', 'void', 'any'}

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
            elif self.peek().type == 'LIBINCLUDE':
                decls.append(self.parse_libinclude())
            elif self.peek().type == 'DETECT':
                decls.append(self.parse_detect_once())
            elif self.peek().type == 'HASH':
                decls.append(self.parse_directive())
            elif self.peek().type == 'STRUCT':
                decls.append(self.parse_struct_decl())
            elif self.peek().type == 'ENUM':
                decls.append(self.parse_enum_decl())
            elif self.peek().type == 'TYPE':
                decls.append(self.parse_type_decl())
            elif self.peek().type == 'LET':
                decls.append(self.parse_let_decl())
            elif self.peek().type == 'MACRO':
                decls.append(self.parse_macro())
            elif self.peek().type == 'TYPEOP':
                decls.append(self.parse_typeop())
            else:
                decls.append(self.parse_decl())
        return decls

    def parse_directive(self):
        loc = self._loc()
        self.consume('HASH')
        name = self.consume('ID').value
        # For now, only namespaces is supported
        if name == 'namespaces':
            val = int(self.consume('NUMBER').value)
            self.consume('SEMI')
            return ('directive', 'namespaces', val, loc)
        else:
            raise SyntaxError(f"Unknown directive #{name} at line {loc[0]}")

    def parse_detect_once(self):
        loc = self._loc()
        self.consume('DETECT')
        self.consume('ONCE')
        self.consume('SEMI')
        return ('detect_once', loc)

    def parse_let_decl(self):
        loc = self._loc()
        self.consume('LET')
        ty = self.parse_type()
        name = self.consume('ID').value
        # Parse any array brackets (C-style fixed-size arrays)
        while self.peek().type == 'LBRACKET':
            self.consume('LBRACKET')
            if self.peek().type != 'NUMBER':
                raise SyntaxError(f"Expected integer literal for array size at line {self.peek().line}")
            size_val = self.consume('NUMBER').value
            self.consume('RBRACKET')
            ty = f"{ty}[{size_val}]"
        if self.peek().type == 'SEMI':
            # No initializer - zero initialization
            self.consume('SEMI')
            return ('pub_var', ty, name, None, loc)
        if self.peek().type == 'CONST_ASSIGN':
            self.consume('CONST_ASSIGN')
            ty = f"const {ty}"
        else:
            self.consume('ASSIGN')
        if self.peek().type == 'LBRACE':
            # Array or struct initializer list
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
            init = ('init_list', init_list)
        else:
            init = self.parse_expr()
        self.consume('SEMI')
        return ('pub_var', ty, name, init, loc)

    def parse_struct_decl(self):
        loc = self._loc()
        self.consume('STRUCT')
        name = self.consume('ID').value
        self.type_names.add(name)
        self.consume('LBRACE')
        fields = []
        while self.peek().type != 'RBRACE':
            fty = self.parse_type()
            fname = self.consume('ID').value
            fields.append((fty, fname))
            while self.peek().type == 'COMMA':
                self.consume('COMMA')
                fname = self.consume('ID').value
                fields.append((fty, fname))
            self.consume('SEMI')
        self.consume('RBRACE')
        self.consume('SEMI')
        return ('struct_decl', name, fields, loc)

    def parse_enum_decl(self):
        loc = self._loc()
        self.consume('ENUM')
        name = self.consume('ID').value
        self.type_names.add(name)  # Register enum name as a known type
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

    def parse_type_decl(self):
        loc = self._loc()
        self.consume('TYPE')
        name = self.consume('ID').value
        self.type_names.add(name)  # Register typedef name as a known type
        self.consume('LBRACE')
        types = []
        if self.peek().type != 'RBRACE':
            while True:
                types.append(self.parse_type())
                if self.peek().type == 'COMMA':
                    self.consume('COMMA')
                else:
                    break
        self.consume('RBRACE')
        self.consume('SEMI')
        return ('type_decl', name, types, loc)

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
    
    def parse_typeop(self):
        loc = self._loc()
        self.consume('TYPEOP')
        # Parse the type name (ID or namespaced ID)
        type_name_tok = self.consume('ID')
        type_name = type_name_tok.value
        if self.peek().type == 'COLONCOLON':
            self.consume('COLONCOLON')
            type_name += '::' + self.consume('ID').value
        # Now parse the operator/method name
        # It could be an operator token (==, !=, +, -, etc.) or a method (dot followed by ID)
        op = None
        if self.peek().type == 'DOT':
            # Method definition: .methodName
            self.consume('DOT')
            if self.peek().type != 'ID':
                raise SyntaxError(f"Expected method name after '.' in typeop at line {self.peek().line}")
            op_tok = self.consume('ID')
            op = op_tok.value
        elif self.peek().type in ('EQ', 'NEQ', 'PLUS', 'MINUS', 'MUL', 'DIV', 'MOD',
                                'LT', 'GT', 'LEQ', 'GEQ', 'AND', 'OR', 'BAND', 'BOR', 'BXOR',
                                'LSHIFT', 'RSHIFT', 'LAND', 'LOR'):
            op_tok = self.consume()
            op = op_tok.value
        elif self.peek().type == 'ID':
            op_tok = self.consume()
            op = op_tok.value
        else:
            raise SyntaxError(f"Expected operator or method name after typeop type at line {self.peek().line}")
        # Parse parameters
        self.consume('LPAREN')
        params = []
        if self.peek().type != 'RPAREN':
            while True:
                pty = self.parse_type()
                pname = self.consume('ID').value
                params.append((pty, pname))
                if self.peek().type == 'COMMA':
                    self.consume('COMMA')
                else:
                    break
        self.consume('RPAREN')
        # Parse body: either a semicolon (declaration) or a brace-enclosed body (definition)
        if self.peek().type == 'SEMI':
            # Declaration only (no body) - used in header files
            self.consume('SEMI')
            body = None  # Indicate no body provided
        elif self.peek().type == 'LBRACE':
            # Full definition with body
            self.consume('LBRACE')
            body = []
            while self.peek().type != 'RBRACE':
                # Similar to macro body, can have statements or expressions
                if self.peek().type in ('IF', 'WHILE', 'FOR', 'DO', 'RETURN', 'VOID', 'SIGNED', 'UNSIGNED') or \
                   (self.peek().type == 'ID' and self._is_decl_start()):
                    body.append(self.parse_stmt())
                else:
                    expr = self.parse_expr()
                    if self.peek().type == 'SEMI':
                        self.consume('SEMI')
                        body.append(('expr_stmt', expr, loc))
                    else:
                        body.append(('expr_stmt', expr, loc))
            self.consume('RBRACE')
        else:
            raise SyntaxError(f"Expected ';' or '{{' after typeop parameters at line {self.peek().line}")
        return ('typeop', type_name, op, params, body, loc)
    
    def _is_decl_start(self):
        """Check if current position starts a declaration (for macro parsing)."""
        pos = self.pos
        if self.peek().type != 'ID':
            return False
        # Skip base type ID
        look = pos + 1
        # Handle namespaced types: skip :: and following ID repeatedly
        while look < len(self.tokens) and self.tokens[look].type == 'COLONCOLON':
            look += 1  # skip COLONCOLON
            if look < len(self.tokens) and self.tokens[look].type == 'ID':
                look += 1  # skip the ID after ::
            else:
                break
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
    
    def _can_start_unary(self, token):
        """Check if a token can start a unary expression (operand of a cast)."""
        if token is None:
            return False
        return token.type in ('BANG', 'TILDE', 'MUL', 'AMP', 'PLUS', 'MINUS',
                              'LPAREN', 'FLOAT', 'NUMBER', 'CHAR', 'STRING',
                              'FNCT', 'ID', 'LBRACE')
    
    def _is_valid_type_for_cast(self, ty_str):
        """Determine if a parsed type string is valid as a cast target."""
        # If it contains '<', '::', or ends with '*', it's clearly a type syntax
        if '<' in ty_str or '::' in ty_str or ty_str.endswith('*'):
            return True
        # Strip modifiers (const, signed, unsigned)
        candidate = ty_str
        while candidate.startswith('const ') or candidate.startswith('signed ') or candidate.startswith('unsigned '):
            if candidate.startswith('const '):
                candidate = candidate[6:]
            elif candidate.startswith('signed '):
                candidate = candidate[7:]
            else:
                candidate = candidate[9:]
        # Check if candidate is a built-in type or a known user-defined type
        if candidate in ('int', 'char', 'float', 'string', 'void', 'any'):
            return True
        if candidate in self.type_names:
            return True
        return False
    
    def parse_include(self):
        self.consume('INCLUDE')
        fname = self.parse_angled_path()
        return ('include', fname)

    def parse_angled_path(self):
        """Parse a path inside <...> brackets, allowing slashes and dots."""
        self.consume('LT')
        parts = []
        while self.peek().type != 'GT':
            parts.append(self.consume().value)
        self.consume('GT')
        return ''.join(parts)

    def parse_libinclude(self):
        loc = self._loc()
        self.consume('LIBINCLUDE')
        path = self.parse_angled_path()
        libtype = None
        # Optional #static or #dynamic
        if self.peek().type == 'HASH':
            self.consume('HASH')
            if self.peek().type == 'ID':
                libtype = self.consume('ID').value
        return ('libinclude', path, libtype, loc)

    def parse_type(self):
        # Handle signed/unsigned/const modifiers
        sign_modifier = None
        const_modifier = False
        # Loop to allow any combination and order of modifiers
        while True:
            if self.peek().type == 'SIGNED':
                self.consume('SIGNED')
                sign_modifier = 'signed'
            elif self.peek().type == 'UNSIGNED':
                self.consume('UNSIGNED')
                sign_modifier = 'unsigned'
            elif self.peek().type == 'CONST':
                self.consume('CONST')
                const_modifier = True
            else:
                break
        
        if self.peek().type == 'VOID':
            self.consume('VOID')
            base = 'void'
        elif self.peek().type == 'ANY':
            self.consume('ANY')
            base = 'any'
        else:
            base = self.consume('ID').value
            if self.peek().type == 'COLONCOLON':
                self.consume('COLONCOLON')
                base += '::' + self.consume('ID').value
            
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
        
        # Apply const modifier to the type
        if const_modifier:
            base = f"const {base}"
        
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

    def _parse_body_or_single(self):
        """Parse either a braced block or a single statement."""
        if self.peek().type == 'LBRACE':
            self.consume('LBRACE')
            body = []
            while self.peek().type != 'RBRACE':
                body.append(self.parse_stmt())
            self.consume('RBRACE')
            return body
        else:
            return [self.parse_stmt()]

    def parse_if_stmt(self):
        loc = self._loc()
        self.consume('IF')
        self.consume('LPAREN')
        cond = self.parse_expr()
        self.consume('RPAREN')
        body = self._parse_body_or_single()
        
        else_body = None
        if self.peek().type == 'ELSE':
            self.consume('ELSE')
            if self.peek().type == 'IF':
                else_body = [self.parse_if_stmt()]
            else:
                else_body = self._parse_body_or_single()
        return ('if_stmt', cond, body, else_body, loc)

    def parse_unless_stmt(self):
        loc = self._loc()
        self.consume('UNLESS')
        self.consume('LPAREN')
        cond = self.parse_expr()
        self.consume('RPAREN')
        body = self._parse_body_or_single()
        
        else_body = None
        if self.peek().type == 'ELSE':
            self.consume('ELSE')
            if self.peek().type == 'IF':
                else_body = [self.parse_if_stmt()]
            else:
                else_body = self._parse_body_or_single()
        negated_cond = ('unary', '!', cond, loc)
        return ('if_stmt', negated_cond, body, else_body, loc)

    def parse_while_stmt(self):
        loc = self._loc()
        self.consume('WHILE')
        self.consume('LPAREN')
        cond = self.parse_expr()
        self.consume('RPAREN')
        body = self._parse_body_or_single()
        return ('while_stmt', cond, body, loc)

    def parse_do_while_stmt(self):
        loc = self._loc()
        self.consume('DO')
        body = self._parse_body_or_single()
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
        body = self._parse_body_or_single()
        return ('for_stmt', init, cond, inc, body, loc)

    def parse_with_stmt(self):
        loc = self._loc()
        self.consume('WITH')
        self.consume('LPAREN')
        expr = self.parse_expr()
        self.consume('AS')
        ty = self.parse_type()
        name = self.consume('ID').value
        self.consume('RPAREN')
        body = self._parse_body_or_single()
        return ('with_stmt', expr, ty, name, body, loc)

    def parse_foreach_stmt(self):
        loc = self._loc()
        self.consume('FOREACH')
        self.consume('LPAREN')
        index_var = self.consume('ID').value
        self.consume('COMMA')
        value_var = self.consume('ID').value
        self.consume('IN')
        array_expr = self.parse_expr()
        self.consume('RPAREN')
        body = self._parse_body_or_single()
        return ('foreach_stmt', index_var, value_var, array_expr, body, loc)

    def parse_forstruct_stmt(self):
        loc = self._loc()
        self.consume('FORSTRUCT')
        self.consume('LPAREN')
        field_var = self.consume('ID').value
        self.consume('COMMA')
        name_var = self.consume('ID').value
        self.consume('IN')
        struct_expr = self.parse_expr()
        self.consume('RPAREN')
        body = self._parse_body_or_single()
        return ('forstruct_stmt', field_var, name_var, struct_expr, body, loc)

    def parse_switch_stmt(self):
        loc = self._loc()
        self.consume('SWITCH')
        self.consume('LPAREN')
        cond = self.parse_expr()
        self.consume('RPAREN')
        self.consume('LBRACE')
        cases = []
        default_body = None
        while self.peek().type != 'RBRACE':
            if self.peek().type == 'CASE':
                self.consume('CASE')
                case_val = self.parse_expr()
                self.consume('COLON')
                body = []
                # Parse statements until we hit another CASE, DEFAULT, or RBRACE
                while self.peek().type not in ('CASE', 'DEFAULT', 'RBRACE'):
                    body.append(self.parse_stmt())
                cases.append(('case', case_val, body, loc))
            elif self.peek().type == 'DEFAULT':
                self.consume('DEFAULT')
                self.consume('COLON')
                default_body = []
                while self.peek().type != 'RBRACE':
                    default_body.append(self.parse_stmt())
            else:
                raise SyntaxError(f"Unexpected token {self.peek().type} in switch body at line {self.peek().line}")
        self.consume('RBRACE')
        return ('switch_stmt', cond, cases, default_body, loc)

    def parse_break_stmt(self):
        loc = self._loc()
        self.consume('BREAK')
        self.consume('SEMI')
        return ('break_stmt', loc)

    def parse_try_catch_stmt(self):
        loc = self._loc()
        self.consume('TRY')
        try_body = self._parse_body_or_single()
        
        self.consume('CATCH')
        self.consume('LPAREN')
        catch_param = self.consume('ID').value
        self.consume('RPAREN')
        catch_body = self._parse_body_or_single()
        
        return ('try_catch_stmt', try_body, catch_param, catch_body, loc)

    def parse_stmt(self):
        if self.peek().type == 'IF':
            return self.parse_if_stmt()
        if self.peek().type == 'UNLESS':
            return self.parse_unless_stmt()
        if self.peek().type == 'WITH':
            return self.parse_with_stmt()
        if self.peek().type == 'SWITCH':
            return self.parse_switch_stmt()
        if self.peek().type == 'WHILE':
            return self.parse_while_stmt()
        if self.peek().type == 'FOR':
            return self.parse_for_stmt()
        if self.peek().type == 'FOREACH':
            return self.parse_foreach_stmt()
        if self.peek().type == 'FORSTRUCT':
            return self.parse_forstruct_stmt()
        if self.peek().type == 'DO':
            return self.parse_do_while_stmt()
        if self.peek().type == 'BREAK':
            return self.parse_break_stmt()
        if self.peek().type == 'TRY':
            return self.parse_try_catch_stmt()
        
        loc = self._loc()
        is_decl = False
        pos = self.pos
        # Check for signed/unsigned/const modifiers, or type keywords (void, any)
        if self.peek().type in ('SIGNED', 'UNSIGNED', 'CONST', 'VOID', 'ANY'):
            is_decl = True
        elif self.peek().type == 'ID':
            # Skip base type ID
            look = pos + 1
            # Handle namespaced types: skip :: and following ID repeatedly
            while look < len(self.tokens) and self.tokens[look].type == 'COLONCOLON':
                look += 1  # skip COLONCOLON
                if look < len(self.tokens) and self.tokens[look].type == 'ID':
                    look += 1  # skip the ID after ::
                else:
                    break
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
            # Parse any array brackets (C-style fixed-size arrays)
            while self.peek().type == 'LBRACKET':
                self.consume('LBRACKET')
                if self.peek().type != 'NUMBER':
                    raise SyntaxError(f"Expected integer literal for array size at line {self.peek().line}")
                size_val = self.consume('NUMBER').value
                self.consume('RBRACKET')
                ty = f"{ty}[{size_val}]"
            if self.peek().type == 'SEMI':
                self.consume('SEMI')
                return ('var_decl', ty, name, None, loc)
            if self.peek().type == 'CONST_ASSIGN':
                self.consume('CONST_ASSIGN')
                ty = f"const {ty}"
            else:
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
        left = self.parse_logical_or()
        # Check for ternary operator (condition ? true_expr : false_expr)
        if self.peek().type == 'QUESTION':
            self.consume('QUESTION')
            true_expr = self.parse_expr()
            self.consume('COLON')
            false_expr = self.parse_expr()
            return ('ternary', left, true_expr, false_expr, loc)
        tok = self.peek()
        if tok.type == 'ASSIGN':
            self.consume('ASSIGN')
            right = self.parse_expr()
            return ('assign', left, right, loc)
        elif tok.type in ('PLUS_ASSIGN', 'MINUS_ASSIGN', 'MUL_ASSIGN', 'DIV_ASSIGN', 'MOD_ASSIGN',
                          'LSHIFT_ASSIGN', 'RSHIFT_ASSIGN', 'AND_ASSIGN', 'OR_ASSIGN', 'XOR_ASSIGN'):
            # Map compound assignment token to base operator
            op_map = {
                'PLUS_ASSIGN': '+',
                'MINUS_ASSIGN': '-',
                'MUL_ASSIGN': '*',
                'DIV_ASSIGN': '/',
                'MOD_ASSIGN': '%',
                'LSHIFT_ASSIGN': '<<',
                'RSHIFT_ASSIGN': '>>',
                'AND_ASSIGN': '&',
                'OR_ASSIGN': '|',
                'XOR_ASSIGN': '^',
            }
            token_type = tok.type
            self.consume()  # consume compound assign token
            right = self.parse_expr()
            return ('compound_assign', left, op_map[token_type], right, loc)
        return left

    def parse_logical_or(self):
        loc = self._loc()
        left = self.parse_logical_and()
        while self.peek().type == 'LOR':
            self.consume('LOR')
            right = self.parse_logical_and()
            left = ('binop', '||', left, right, loc)
        return left

    def parse_logical_and(self):
        loc = self._loc()
        left = self.parse_bitwise_or()
        while self.peek().type == 'LAND':
            self.consume('LAND')
            right = self.parse_bitwise_or()
            left = ('binop', '&&', left, right, loc)
        return left

    def parse_bitwise_or(self):
        loc = self._loc()
        left = self.parse_bitwise_xor()
        while self.peek().type == 'BOR':
            self.consume('BOR')
            right = self.parse_bitwise_xor()
            left = ('binop', '|', left, right, loc)
        return left

    def parse_bitwise_xor(self):
        loc = self._loc()
        left = self.parse_bitwise_and()
        while self.peek().type == 'BXOR':
            self.consume('BXOR')
            right = self.parse_bitwise_and()
            left = ('binop', '^', left, right, loc)
        return left

    def parse_bitwise_and(self):
        loc = self._loc()
        left = self.parse_equality()
        while self.peek().type == 'AMP':
            self.consume('AMP')
            right = self.parse_equality()
            left = ('binop', '&', left, right, loc)
        return left

    def parse_equality(self):
        loc = self._loc()
        left = self.parse_relational()
        while self.peek().type in ('EQ', 'NEQ'):
            op = self.consume().value
            right = self.parse_relational()
            left = ('binop', op, left, right, loc)
        return left

    def parse_relational(self):
        loc = self._loc()
        left = self.parse_shift()
        while self.peek().type in ('GT', 'LT', 'LEQ', 'GEQ'):
            op = self.consume().value
            right = self.parse_shift()
            left = ('binop', op, left, right, loc)
        return left

    def parse_shift(self):
        loc = self._loc()
        left = self.parse_arithmetic()
        while True:
            if self.peek().type == 'LSHIFT':
                op = self.consume().value
                right = self.parse_arithmetic()
                left = ('binop', op, left, right, loc)
            elif self.peek().type == 'GT':
                # Check for two consecutive '>' to form right shift
                if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].type == 'GT':
                    self.consume('GT')
                    self.consume('GT')
                    op = '>>'
                    right = self.parse_arithmetic()
                    left = ('binop', op, left, right, loc)
                else:
                    break
            else:
                break
        return left

    def parse_arithmetic(self):
        loc = self._loc()
        left = self.parse_multiplicative()
        while self.peek().type in ('PLUS', 'MINUS'):
            op = self.consume().value
            right = self.parse_multiplicative()
            left = ('binop', op, left, right, loc)
        return left

    def parse_multiplicative(self):
        loc = self._loc()
        left = self.parse_unary()
        while self.peek().type in ('MUL', 'DIV', 'MOD'):
            op = self.consume().value
            right = self.parse_unary()
            left = ('binop', op, left, right, loc)
        return left

    def parse_unary(self):
        loc = self._loc()
        # Check for sizeof
        if self.peek().type == 'SIZEOF':
            self.consume('SIZEOF')
            # sizeof requires parentheses
            if self.peek().type != 'LPAREN':
                raise SyntaxError(f"Expected '(' after sizeof at line {self.peek().line}")
            self.consume('LPAREN')
            # Determine if we're sizing a type or an expression
            saved_pos = self.pos
            try:
                ty = self.parse_type()
                # Check if followed by RPAREN - if so, it's a candidate for type
                if self.peek().type == 'RPAREN':
                    # Disambiguate: if ty is a simple identifier not in type_names, treat as expression.
                    is_simple_ident = ty.isidentifier() and not any(c in ty for c in ' <>*&')
                    if is_simple_ident and ty not in self.type_names:
                        # Not a known type; rollback and parse as expression
                        self.pos = saved_pos
                        expr = self.parse_expr()
                        if self.peek().type != 'RPAREN':
                            raise SyntaxError(f"Expected ')' after sizeof expression at line {self.peek().line}")
                        self.consume('RPAREN')
                        return ('sizeof_expr', expr, loc)
                    else:
                        # It's a valid type
                        self.consume('RPAREN')
                        return ('sizeof_type', ty, loc)
                # Not followed by RPAREN, rollback and parse as expression
                self.pos = saved_pos
            except SyntaxError:
                self.pos = saved_pos
            # Must be an expression
            expr = self.parse_expr()
            if self.peek().type != 'RPAREN':
                raise SyntaxError(f"Expected ')' after sizeof expression at line {self.peek().line}")
            self.consume('RPAREN')
            return ('sizeof_expr', expr, loc)
        # Check for gettype
        if self.peek().type == 'GETTYPE':
            self.consume('GETTYPE')
            # gettype requires parentheses
            if self.peek().type != 'LPAREN':
                raise SyntaxError(f"Expected '(' after gettype at line {self.peek().line}")
            self.consume('LPAREN')
            # gettype always takes an expression
            expr = self.parse_expr()
            if self.peek().type != 'RPAREN':
                raise SyntaxError(f"Expected ')' after gettype expression at line {self.peek().line}")
            self.consume('RPAREN')
            return ('gettype', expr, loc)
        # Check for cast: (type) unary_expression
        if self.peek().type == 'LPAREN':
            saved_pos = self.pos
            self.consume('LPAREN')
            try:
                ty = self.parse_type()
                if self.peek().type == 'RPAREN':
                    # Validate that this looks like a type for casting
                    if self._is_valid_type_for_cast(ty):
                        # Check the token after RPAREN to see if it can start a unary expression
                        # Peek ahead without consuming
                        if self.pos + 1 < len(self.tokens):
                            next_tok = self.tokens[self.pos + 1]
                        else:
                            next_tok = None
                        if next_tok and self._can_start_unary(next_tok):
                            self.consume('RPAREN')
                            operand = self.parse_unary()
                            return ('cast', ty, operand, loc)
            except SyntaxError:
                pass
            # Not a cast, rollback to before '('
            self.pos = saved_pos
        # Handle unary operators (including prefix ++/--)
        if self.peek().type in ('BANG', 'TILDE', 'MUL', 'AMP', 'PLUS', 'MINUS', 'INCREMENT', 'DECREMENT'):
            op = self.consume().value
            target = self.parse_unary()
            if op == '++':
                return ('pre_inc', target, loc)
            elif op == '--':
                return ('pre_dec', target, loc)
            return ('unary', op, target, loc)
        return self.parse_primary()

    def parse_syscall_expr(self):
        loc = self._loc()
        self.consume('SYSCALL')
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
        return ('syscall', args, loc)

    def parse_primary(self):
        loc = self._loc()
        if self.peek().type == 'LPAREN':
            self.consume('LPAREN')
            target = self.parse_expr()
            self.consume('RPAREN')
        elif self.peek().type == 'SYSCALL':
            return self.parse_syscall_expr()
        elif self.peek().type == 'FLOAT':
            target = ('float', float(self.consume('FLOAT').value), loc)
        elif self.peek().type == 'NUMBER':
            target = ('number', int(self.consume('NUMBER').value), loc)
        elif self.peek().type == 'CHAR':
            target = ('char', self.consume('CHAR').value, loc)
        elif self.peek().type == 'STRING':
            target = ('string', self.consume('STRING').value, loc)
        elif self.peek().type == 'FNCT':
            # Lambda expression: fnct(params) { body }
            self.consume('FNCT')
            self.consume('LPAREN')
            params = []
            if self.peek().type != 'RPAREN':
                while True:
                    pty = self.parse_type()
                    pname = self.consume('ID').value
                    params.append((pty, pname))
                    if self.peek().type == 'COMMA':
                        self.consume('COMMA')
                    else:
                        break
            self.consume('RPAREN')
            self.consume('LBRACE')
            body = []
            while self.peek().type != 'RBRACE':
                body.append(self.parse_stmt())
            self.consume('RBRACE')
            target = ('lambda', params, body, loc)
        elif self.peek().type == 'NULL':
            self.consume('NULL')
            target = ('null', loc)
        elif self.peek().type == 'ID':
            parts = [self.consume('ID').value]
            while self.peek().type == 'COLONCOLON':
                self.consume('COLONCOLON')
                parts.append(self.consume('ID').value)
            if len(parts) == 1:
                # Check if this is gettype followed by LPAREN
                if parts[0] == 'gettype' and self.peek().type == 'LPAREN':
                    # Parse as gettype expression
                    self.consume('LPAREN')
                    expr = self.parse_expr()
                    if self.peek().type != 'RPAREN':
                        raise SyntaxError(f"Expected ')' after gettype expression at line {self.peek().line}")
                    self.consume('RPAREN')
                    target = ('gettype', expr, loc)
                else:
                    target = ('id', parts[0], loc)
            else:
                base = '::'.join(parts[:-1])
                name = parts[-1]
                target = ('namespace_access', base, name, loc)
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
            if self.peek().type == 'COLONCOLON':
                self.consume('COLONCOLON')
                name = self.consume('ID').value
                target = ('namespace_access', target, name, loc)
            elif self.peek().type == 'DOT':
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
            elif self.peek().type in ('INCREMENT', 'DECREMENT'):
                op = self.consume().value
                if op == '++':
                    target = ('post_inc', target, loc)
                else:
                    target = ('post_dec', target, loc)
            else:
                break
        return target
