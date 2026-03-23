;;; c5-mode.el --- Major mode for the C5 programming language -*- lexical-binding: t -*-

;; Copyright (C) 2026 Gemini CLI
;; Author: Gemini CLI
;; Keywords: languages

;;; Commentary:
;; This mode provides syntax highlighting and basic indentation for the C5
;; programming language.

;;; Code:

(defvar c5-mode-syntax-table
  (let ((st (make-syntax-table)))
    ;; C-style comments: // and /* */
    (modify-syntax-entry ?/ ". 124b" st)
    (modify-syntax-entry ?* ". 23" st)
    (modify-syntax-entry ?\n "> b" st)
    ;; Strings
    (modify-syntax-entry ?\" "\"" st)
    (modify-syntax-entry ?\\ "\\" st)
    ;; Characters
    (modify-syntax-entry ?\' "\"" st)
    st)
  "Syntax table for `c5-mode'.")

(defvar c5-keywords
  '("include" "libinclude" "let" "const" "macro" "type" "typeop" "fnct"
    "if" "else" "unless" "switch" "case" "default" "with" "as"
    "while" "do" "for" "foreach" "forever" "in" "break" "syscall"
    "return" "try" "catch" "struct" "enum" "signed" "unsigned"
    "forstruct" "delete")
  "Keywords for C5.")

(defvar c5-constants
  '("NULL")
  "Constants for C5.")

(defvar c5-types
  '("void" "int" "float" "char" "string" "array" "any")
  "Built-in types for C5.")

(defvar c5-methods
  '("push" "pop" "length" "insert" "insertItems" "clear" "replace")
  "Built-in methods for arrays and strings in C5.")

(defvar c5-font-lock-keywords
  (list
   ;; Includes with filenames
   '("^\\s-*\\(?:lib\\)?include\\s-+<\\([^>]+\\)>" (1 font-lock-string-face))
   ;; Preprocessor-like directives (#static, #dynamic, #namespaces)
   '("#[a-zA-Z_]+" . font-lock-preprocessor-face)
   ;; Keywords
   (cons (regexp-opt c5-keywords 'words) font-lock-keyword-face)
   ;; Constants (NULL, etc.)
   (cons (regexp-opt c5-constants 'words) font-lock-constant-face)
   ;; Built-in types
   (cons (regexp-opt c5-types 'words) font-lock-type-face)
   ;; Built-in methods
   (cons (concat "\\." (regexp-opt c5-methods 'words)) font-lock-builtin-face)
   ;; C-style array definitions: type name[size] or type name[size] = {...}
   '("\\<\\([a-zA-Z_][a-zA-Z0-9_]*\\(?:<[^>]*>\\)*\\)\\s-+\\([a-zA-Z_][a-zA-Z0-9_]*\\)\\s*\\[[^]]+\\]"
     (1 font-lock-type-face)
     (2 font-lock-variable-name-face))
   ;; Parameterized types (e.g., int<32>, array<int>, array<array<int>>)
   '("\\<[a-zA-Z_][a-zA-Z0-9_]*<[^>]+>" . font-lock-type-face)
   ;; Namespace resolution (e.g., std::printf)
   '("\\<\\([a-zA-Z_][a-zA-Z0-9_]*\\)::\\([a-zA-Z0-9_]*\\)"
     (1 font-lock-constant-face)
     (2 font-lock-function-name-face))
   ;; Type operator definitions: typeop TypeName.operator or typeop TypeName operator
   '("\\<typeop\\s-+\\([a-zA-Z_][a-zA-Z0-9_]*\\)\\s+\\(\\(?:==\\|!=\\|<=\\|>=\\|&&\\|||\\|<<\\|>>\\|->\\|\\.\\.\\.\\|[+\\-*/%&|^~=<>!]\\|\\.[a-zA-Z_][a-zA-Z0-9_]*\\)\\)\\s-*("
     (1 font-lock-type-face)
     (2 font-lock-function-name-face))
   ;; Function definitions (with return type, possibly generic/pointer)
   '("\\<\\([a-zA-Z_][a-zA-Z0-9_]*\\(?:<[^>]*>\\)*\\*?\\)\\s-+\\([a-zA-Z_][a-zA-Z0-9_]*\\)\\s-*("
     (1 font-lock-type-face)
     (2 font-lock-function-name-face))
   ;; Function calls (not definition)
   '("\\<\\([a-zA-Z_][a-zA-Z0-9_]*\\)\\s-*("
     (1 font-lock-function-name-face))
   ;; Constants (integers and floats)
   '("\\<[0-9]+\\(?:\\.[0-9]+\\)?\\(?:[eE][+-]?[0-9]+\\)?\\>" . font-lock-constant-face)
   '("\\<0x[0-9a-fA-F]+\\>" . font-lock-constant-face)
    ;; Operators and member access
    '("->\\|\\.\\|::" . font-lock-keyword-face)
    '(":=\\|\\+\\+\\|--\\|\\+=\\|-=\\|\\*=\\|/=\\|%=\\|<<=\\|>>=\\|&=\\||=\\|\\^=\\|==\\|!=\\|<=\\|>=\\|&&\\|\\|\\|\\|<<\\|>>\\|\\.\\.\\.\\|?" . font-lock-comment-delimiter-face)
    )
  "Font-lock keywords for `c5-mode'.")

;;;###autoload
(define-derived-mode c5-mode prog-mode "C5"
  "Major mode for editing C5 files."
  :syntax-table c5-mode-syntax-table
  (setq-local font-lock-defaults '(c5-font-lock-keywords))
  (setq-local comment-start "// ")
  (setq-local comment-end "")
  ;; Basic indentation based on brackets
  (setq-local indent-line-function 'indent-relative)
  (setq-local indent-tabs-mode nil))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.c5\\'" . c5-mode))
;;;###autoload
(add-to-list 'auto-mode-alist '("\\.c5h\\'" . c5-mode))

(provide 'c5-mode)

;;; c5-mode.el ends here
