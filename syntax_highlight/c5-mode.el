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
  '("include" "libinclude" "let" "const" "macro" "type" "fnct"
    "if" "else" "switch" "case" "default"
    "while" "do" "for" "foreach" "in" "break"
    "return" "try" "catch" "#static" "#dynamic")
  "Keywords for C5.")

(defvar c5-types
  '("void" "int" "float" "char" "string" "array" "signed" "unsigned")
  "Built-in types for C5.")

(defvar c5-font-lock-keywords
  (list
   ;; Keywords
   (cons (regexp-opt c5-keywords 'words) font-lock-keyword-face)
   ;; Built-in types
   (cons (regexp-opt c5-types 'words) font-lock-type-face)
   ;; Parameterized types like int<32> or float<64>
   '("\\<\\(int\\|float\\)<[0-9]+>\\>" . font-lock-type-face)
   ;; Structs and Enums
   '("\\<\\(struct\\|enum\\)\\>\\s-+\\([a-zA-Z_][a-zA-Z0-9_]*\\)"
     (1 font-lock-keyword-face)
     (2 font-lock-variable-name-face))
   ;; Function definitions
   '("\\<\\([a-zA-Z_][a-zA-Z0-9_]*\\)\\s-*("
     (1 font-lock-function-name-face))
   ;; Namespace resolution
   '("\\<\\([a-zA-Z_][a-zA-Z0-9_]*\\)::"
     (1 font-lock-constant-face))
   ;; Constants (integers and floats)
   '("\\<[0-9]+\\(?:\\.[0-9]+\\)?\\>" . font-lock-constant-face)
   '("\\<0x[0-9a-fA-F]+\\>" . font-lock-constant-face))
  "Font-lock keywords for `c5-mode'.")

;;;###autoload
(define-derived-mode c5-mode prog-mode "C5"
  "Major mode for editing C5 files."
  :syntax-table c5-mode-syntax-table
  (setq-local font-lock-defaults '(c5-font-lock-keywords))
  (setq-local comment-start "// ")
  (setq-local comment-end "")
  ;; Basic indentation based on brackets
  (setq-local indent-line-function 'indent-relative))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.c5\\'" . c5-mode))
;;;###autoload
(add-to-list 'auto-mode-alist '("\\.c5h\\'" . c5-mode))

(provide 'c5-mode)

;;; c5-mode.el ends here
