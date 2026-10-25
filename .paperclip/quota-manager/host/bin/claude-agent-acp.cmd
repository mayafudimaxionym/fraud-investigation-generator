@echo off
rem Guarded launch entry point for the anthropic provider's ACP protocol server.
rem
rem Paperclip's `claude_local`/`codex_local` adapters default their `engine` to
rem ACP, which starts this program rather than the provider's command-line tool.
rem It is a different program, so it needs its own guard; the sibling CLI wrapper
rem cannot stand in for it.
rem
rem The basename stays "claude-agent-acp" because acpx identifies the ACP lane by this
rem basename with the extension stripped, and only a recognized lane gets its
rem provider-specific launch handling (for Claude, resolving
rem CLAUDE_CODE_EXECUTABLE). Renaming this file would silently change that.
rem
rem stdout belongs to the ACP protocol (newline-delimited JSON-RPC). The guard
rem writes every diagnostic to stderr, which Paperclip captures per run, so a
rem denial is visible without corrupting the protocol stream.
setlocal
set "QM_ROOT=%~dp0..\..\"
set "QM_COMPANY=e6b7cf59-43ee-4b47-82b0-d1a3ed33b26e"
"%QM_ROOT%..\..\Python\bin\python.exe" "%QM_ROOT%quota_manager.py" exec --provider anthropic --engine acp --policy "%QM_ROOT%companies\%QM_COMPANY%\policy.json" --state "%QM_ROOT%companies\%QM_COMPANY%\state.json" -- %*
exit /b %ERRORLEVEL%
