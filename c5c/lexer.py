import re

class Token:
    def __init__(self, type, value, line, column):
        self.type = type
        self.value = value
        self.line = line
        self.column = column
    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)})"

def lex(code):
    token_specification = [
        ('COMMENT',   r'//[^\n]*'),
        ('INCLUDE',   r'include\b'),
        ('VOID',      r'void\b'),
        ('RETURN',    r'return\b'),
        ('IF',        r'if\b'),
        ('ELSE',      r'else\b'),
        ('WHILE',     r'while\b'),
        ('FOR',       r'for\b'),
        ('DO',        r'do\b'),
        ('STRUCT',    r'struct\b'),
        ('ENUM',      r'enum\b'),
        ('LET',       r'let\b'),
        ('SIGNED',    r'signed\b'),
        ('UNSIGNED',  r'unsigned\b'),
        ('ELLIPSIS',  r'\.\.\.'),
        ('DOT',       r'\.'),
        ('COLONCOLON',r'::'),
        ('EQ',        r'=='),
        ('NEQ',       r'!='),
        ('LEQ',       r'<='),
        ('GEQ',       r'>='),
        ('LT',        r'<'),
        ('GT',        r'>'),
        ('LPAREN',    r'\('),
        ('RPAREN',    r'\)'),
        ('LBRACE',    r'\{'),
        ('RBRACE',    r'\}'),
        ('COMMA',     r','),
        ('SEMI',      r';'),
        ('ASSIGN',    r'='),
        ('ARROW',     r'->'),
        ('LBRACKET',  r'\['),
        ('RBRACKET',  r'\]'),
        ('PLUS',      r'\+'),
        ('MINUS',     r'-'),
        ('MUL',       r'\*'),
        ('DIV',       r'/'),
        ('AMP',       r'\&'),
        ('FLOAT',     r'\d+\.\d+'),
        ('NUMBER',    r'\d+'),
        ('CHAR',      r"'(?:\\.|[^'\\])'"),
        ('STRING',    r'"(?:\\.|[^"\\])*"'),
        ('ID',        r'[a-zA-Z_][a-zA-Z0-9_]*'),
        ('NEWLINE',   r'\n'),
        ('SKIP',      r'[ \t\r]+'),
        ('MISMATCH',  r'.'),
    ]
    tok_regex = '|'.join('(?P<%s>%s)' % pair for pair in token_specification)
    line_num = 1
    line_start = 0
    tokens = []
    for mo in re.finditer(tok_regex, code):
        kind = mo.lastgroup
        value = mo.group()
        column = mo.start() - line_start
        if kind == 'NEWLINE':
            line_start = mo.end()
            line_num += 1
            continue
        elif kind == 'SKIP' or kind == 'COMMENT':
            continue
        elif kind == 'MISMATCH':
            raise RuntimeError(f'{value!r} unexpected on line {line_num}')
        if kind == 'STRING':
            real_val = value[1:-1].encode('utf-8').decode('unicode_escape')
            tokens.append(Token(kind, real_val, line_num, column))
        elif kind == 'CHAR':
            real_val = value[1:-1].encode('utf-8').decode('unicode_escape')
            tokens.append(Token(kind, ord(real_val), line_num, column))
        else:
            tokens.append(Token(kind, value, line_num, column))
    tokens.append(Token('EOF', '', line_num, 0))
    return tokens
