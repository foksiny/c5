" Vim syntax file
" Language: C5
" Maintainer: Jose
" URL: https://github.com/yourusername/c5

if exists("b:current_syntax")
  finish
endif

" Keywords
syn keyword c5Keyword include void signed unsigned const let if else while do for foreach in switch case default break struct enum macro fnct type return try catch
syn keyword c5Type int float char string


" Include directive
syn match c5Include '^\s*include\s*[<"]' contains=c5IncludePunct
syn match c5IncludePunct '[<"]' contained

" Numbers
syn match c5Number '\b[0-9]\+\(_\?[0-9]\+\)*\b'
syn match c5Number '\b0x[0-9a-fA-F]\+\(_\?[0-9a-fA-F]\+\)*\b'
syn match c5Number '\b[0-9]\+\.[0-9]*\([eE][-+]?[0-9]\+\)\?\b'

" Strings
syn region c5String start=+"+ skip=+\\\\\|\\"+ end=+"+ contains=c5Escape
syn region c5String start=+'+ skip=+\\\\\|\\'+ end=+'+ contains=c5Escape
syn match c5Escape '\\[abfnrtv\\"']' contained
syn match c5Escape '\\x\x\{2}' contained
syn match c5Escape '\\u\x\{4}' contained
syn match c5Escape '\\U\x\{8}' contained

" Comments
syn region c5Comment start='/\*' end='\*/' contains=c5Todo
syn region c5Comment start='//' end='$' contains=c5Todo

" Todo
syn keyword c5Todo TODO FIXME XXX NOTE HACK contained

" Labels (for case statements)
syn match c5Label '^\s*[a-zA-Z_][a-zA-Z0-9_]*\s*:' contains=c5LabelPunct
syn match c5LabelPunct ':' contained

" Operators
syn match c5Operator '[=!<>]=\|<<\|>>\|&&|||[&|^~+*/%-]'

" Delimiters
syn match c5Delimiter '[(){}[\],.;]'

" Namespace resolution
syn match c5Namespace '::'

" Arrow operator
syn match c5Arrow '->'

" Type parameters (angle brackets)
syn match c5TypeParam '<[^>]*>' contains=c5TypeParamPunct
syn match c5TypeParamPunct '[<>]' contained

" User-defined type names (struct, enum, type)
syn match c5UserType "\<\(struct\|enum\|type\)\s\+\zs\k\+\ze"
hi def link c5UserType Type

" Ellipsis (...)
syn match c5Ellipsis "\.\.\."
hi def link c5Ellipsis Special

" Function call
syn match c5FunctionCall '\k\+\s*(' contains=c5FunctionCallPunct
syn match c5FunctionCallPunct '(' contained

" Macro definition
syn match c5Macro '^\s*macro\s\+\k\+' contains=c5MacroName
syn match c5MacroName '\k\+' contained

" Highlighting links
hi def link c5Keyword Keyword
hi def link c5Type Type
hi def link c5Include Include
hi def link c5IncludePunct Delimiter
hi def link c5Number Number
hi def link c5String String
hi def link c5Escape SpecialChar
hi def link c5Comment Comment
hi def link c5Todo Todo
hi def link c5Label Label
hi def link c5LabelPunct Delimiter
hi def link c5Operator Operator
hi def link c5Delimiter Delimiter
hi def link c5Namespace Special
hi def link c5Arrow Special
hi def link c5TypeParam Type
hi def link c5TypeParamPunct Delimiter
hi def link c5FunctionCall Function
hi def link c5FunctionCallPunct Delimiter
hi def link c5Macro PreProc
hi def link c5MacroName Function

let b:current_syntax = "c5"

" vim: ft=vim
