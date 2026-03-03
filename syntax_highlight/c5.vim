" Vim syntax file
" Language: C5
" Maintainer: Gemini CLI
" Latest Revision: 2026-03-03

if exists("b:current_syntax")
  finish
endif

" Keywords
syn keyword c5Keyword include libinclude let const macro type fnct
syn keyword c5Keyword #static #dynamic
syn keyword c5Conditional if else switch case default
syn keyword c5Repeat while do for foreach in break
syn keyword c5Statement return try catch
syn keyword c5Structure struct enum
syn keyword c5Type void int float char string array signed unsigned

" Parameterized Types (e.g., int<32>, float<64>)
syn match c5ParameterizedType "\v(int|float)\<\d+\>"

" Namespaces and Operators
syn match c5Namespace "\v[a-zA-Z_][a-zA-Z0-9_]*::"
syn match c5Operator "\v-\>"
syn match c5Operator "\v\."
syn match c5Operator "\v\+\=|\-\=|\*\=|\/\=|\%\=|\&\=|\"|\|\=|\^\=|\<\<\=|\>\>\="
syn match c5Operator "\v\+\+|\-\-"
syn match c5Operator "\v\=\="
syn match c5Operator "\v\!\="
syn match c5Operator "\v\<\="
syn match c5Operator "\v\>\="
syn match c5Operator "\v\&\&"
syn match c5Operator "\v\|\|"
syn match c5Operator "\v[\+\-\*\/\%\=\!\<\>\&\|\^\~\?]"

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
hi def link c5Conditional Conditional
hi def link c5Repeat Repeat
hi def link c5Statement Statement
hi def link c5Structure Structure
hi def link c5Type Type
hi def link c5ParameterizedType Type
hi def link c5Namespace Identifier
hi def link c5Operator Operator
hi def link c5Number Number
hi def link c5Float Float
hi def link c5Hex Number
hi def link c5String String
hi def link c5Character Character
hi def link c5Escape Special
hi def link c5Comment Comment

let b:current_syntax = "c5"
