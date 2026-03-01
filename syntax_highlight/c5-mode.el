;;; c5-mode.el --- Major mode for editing C5 programming language files

;; Author: Jose
;; Version: 1.0
;; Keywords: languages c5
;;; Commentary:

;; Major mode for editing C5 (C5) source code.

;;; Code:

(defgroup c5 nil
  "Major mode for editing C5 code."
  :group 'languages)

(defcustom c5-mode-hook nil
  "Hook run when entering C5 mode."
  :type 'hook
  :group 'c5)

;; Syntax table
(defvar c5-mode-syntax-table
  (let ((table (make-syntax-table)))
    ;; C-style comments
    (modify-syntax-entry ?/ ". 124" table)
    (modify-syntax-entry ?* ". 23b" table)
    (modify-syntax-entry ?\n "> b" table)
    ;; String and character literals
    (modify-syntax-entry ?\" "\"" table)
    (modify-syntax-entry ?\' "\"" table)
    ;; Word constituents
    (modify-syntax-entry ?_ "w" table)
    ;; Parentheses
    (modify-syntax-entry ?\( "()" table)
    (modify-syntax-entry ?\) ")(" table)
    (modify-syntax-entry ?\{ "(}" table)
    (modify-syntax-entry ?\} "){" table)
    (modify-syntax-entry ?\[ "(]" table)
    (modify-syntax-entry ?\] ")[" table)
    ;; Operators
    (modify-syntax-entry ?= "." table)
    (modify-syntax-entry ?< "." table)
    (modify-syntax-entry ?> "." table)
    (modify-syntax-entry ?+ "." table)
    (modify-syntax-entry ?- "." table)
    (modify-syntax-entry ?* "." table)
    (modify-syntax-entry ?/ "." table)
    (modify-syntax-entry ?% "." table)
    (modify-syntax-entry ?& "." table)
    (modify-syntax-entry ?| "." table)
    (modify-syntax-entry ?^ "." table)
    (modify-syntax-entry ?~ "." table)
    (modify-syntax-entry ?! "." table)
    table)
  "Syntax table for `c5-mode'.")

;; Keywords
(defconst c5-keywords
  '("include" "void" "signed" "unsigned" "const" "let" "if" "else" "while"
    "do" "for" "foreach" "in" "switch" "case" "default" "break" "struct"
    "enum" "macro" "fnct" "type" "return" "try" "catch"))

;; Type keywords (parameterized types like int<32>)
(defconst c5-type-keywords
  '("int<8>" "int<16>" "int<32>" "int<64>" "float<32>" "float<64>" "char" "string"))

;; Ellipsis (...)
(defconst c5-ellipsis
  '("\\.\\.\\."))

;; Regular expressions
(defconst c5-font-lock-keywords
  `(
    ;; Comments
    ("/\\*\\([^/*]*\\|\\*[^/]\\)*\\*/" . font-lock-comment-face)
    ("//.*" . font-lock-comment-face)

    ;; Strings and characters
    ("\"[^\"\\]*\\(\\\\.[^\"\\]*\\)*\"" . font-lock-string-face)
    ("'[^'\\]*'" . font-lock-string-face)

    ;; Keywords
    (,(regexp-opt c5-keywords 'words) . font-lock-keyword-face)
;; Types (int<32>, float<64>, etc.)
(,(regexp-opt '("int" "float" "char" "string") 'words) . font-lock-type-face)

;; Struct/Enum/Type definition names
("\\<\\(struct\\|enum\\|type\\)\\>\\s-+\\([a-zA-Z_][a-zA-Z0-9_]*\\)"
 2 font-lock-type-face)

;; Ellipsis (...)
(,(regexp-opt c5-ellipsis) . font-lock-builtin-face)

    ;; Numbers
    ("\\b[0-9]+\\b" . font-lock-constant-face)
    ("\\b0x[0-9a-fA-F]+\\b" . font-lock-constant-face)
    ("\\b[0-9]+\\.[0-9]*\\([eE][-+]?[0-9]+\\)?\\b" . font-lock-constant-face)

    ;; Preprocessor-like include directive
    ("^\\s-*include\\s-+" . font-lock-preprocessor-face)

    ;; Namespace resolution (::)
    ("::" . font-lock-builtin-face)

    ;; Labels (for case statements and goto)
    ("\\b[a-zA-Z_][a-zA-Z0-9_]*\\s-*:" . font-lock-label-face)

    ;; Struct/Enum member access (->)
    ("->" . font-lock-function-call-face)

    ;; Function calls
    ("\\b[a-zA-Z_][a-zA-Z0-9_]*\\s-*(" . (1 font-lock-function-call-face))

    ;; Variables (simple heuristic)
    ("\\b[a-zA-Z_][a-zA-Z0-9_]*\\b" . font-lock-variable-name-face)
    ))

;;;###autoload
(define-derived-mode c5-mode prog-mode "C5"
  "Major mode for editing C5 code."
  :syntax-table c5-mode-syntax-table
  (setq-local font-lock-defaults '(c5-font-lock-keywords))
  (setq-local comment-start "// ")
  (setq-local comment-start-skip "//+\\s-*")
  (setq-local comment-end "")
  (setq-local indent-tabs-mode nil)
  (setq-local c-basic-offset 4))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.c5\\'" . c5-mode))
(add-to-list 'auto-mode-alist '("\\.c5h\\'" . c5-mode))

(provide 'c5-mode)

;;; c5-mode.el ends here
