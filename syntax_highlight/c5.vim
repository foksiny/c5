" Vim syntax file
" Language: C5
" Maintainer: Gemini CLI
" Latest Revision: 2026-03-09

if exists("b:current_syntax")
  finish
endif

" Keywords
syn keyword c5Keyword let const macro type fnct
syn keyword c5Include include libinclude
syn match c5PreProc "\v#[a-zA-Z_]+"
syn keyword c5Conditional if else switch case default
syn keyword c5Repeat while do for foreach in break
syn keyword c5Statement return try catch
syn keyword c5Structure struct enum
syn keyword c5Type void int float char string array signed unsigned
syn keyword c5Constant NULL

" Include files
syn region c5IncludeFile start="\v(include|libinclude)\s+\zs\<" end="\v\>"

" Parameterized Types (e.g., int<32>, float<64>, array<array<T>>)
syn region c5ParameterizedType start="\v[a-zA-Z_][a-zA-Z0-9_]*\<" end="\v\>" contains=c5ParameterizedType,c5Type,c5Number,c5Operator,c5Namespace

" Namespaces and Operators
syn match c5Namespace "\v[a-zA-Z_][a-zA-Z0-9_]*::"
syn match c5Operator "\v\.\.\."
syn match c5Operator "\v-\>"
syn match c5Operator "\v\."
syn match c5Operator "\v\+\=|\-\=|\*\=|\/\=|\%\=|\&\=|\^=|\|\=|\<\<\=|\>\>\="
syn match c5Operator "\v\+\+|\-\-"
syn match c5Operator "\v\=\="
syn match c5Operator "\v\!\="
syn match c5Operator "\v\<\="
syn match c5Operator "\v\>\="
syn match c5Operator "\v\&\&"
syn match c5Operator "\v\|\|"
syn match c5Operator "\v\<\<|\>\>"
syn match c5Operator "\v[\+\-\*\/\%\=\!\<\>\&\|\^\~\.]"

" Functions
syn match c5Function "\v[a-zA-Z_][a-zA-Z0-9_]*\s*\ze\("

" C-style array definitions: match variable name before '['
syn match c5VariableName "\v\<[a-zA-Z_][a-zA-Z0-9_]*\>\ze\["

" Brackets for array indexing/definition
syn match c5Operator "\["
syn match c5Operator "\]"

" Numbers
syn match c5Number "\v<\d+>"
syn match c5Float "\v<\d+\.\d+>"
syn match c5Hex "\v<0x[0-9a-fA-F]+>"

" Strings and Characters
syn region c5String start=/\v"/ skip=/\v\\./ end=/\v"/ contains=c5Escape
syn region c5Character start=/\v'/ skip=/\v\\./ end=/\v'/ contains=c5Escape
syn match c5Escape "\v\\." contained

" Comments
syn match c5Comment "\v\/\/.*$"
syn region c5Comment start=/\v\/\*/ end=/\v\*\//

" Highlighting Links
hi def link c5Keyword Keyword
hi def link c5Include Include
hi def link c5IncludeFile String
hi def link c5PreProc PreProc
hi def link c5Conditional Conditional
hi def link c5Repeat Repeat
hi def link c5Statement Statement
hi def link c5Structure Structure
hi def link c5Type Type
hi def link c5ParameterizedType Type
hi def link c5Namespace Identifier
hi def link c5Operator Operator
hi def link c5Function Function
hi def link c5Number Number
hi def link c5Float Float
hi def link c5Hex Number
hi def link c5String String
hi def link c5Character Character
hi def link c5Escape Special
hi def link c5Comment Comment

let b:current_syntax = "c5"
