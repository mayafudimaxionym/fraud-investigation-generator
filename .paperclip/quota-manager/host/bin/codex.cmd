@echo off
rem Guarded launch entry point for the openai provider CLI.
rem The basename stays "codex" because the Paperclip adapter only applies its
rem minimum-CLI-version preflight when the configured command's basename is the
rem provider's own ("codex", "codex.cmd" or "codex.exe"). Renaming this file
rem would silently disable that preflight.
setlocal
set "QM_ROOT=%~dp0..\..\"
set "QM_COMPANY=e6b7cf59-43ee-4b47-82b0-d1a3ed33b26e"
"%QM_ROOT%..\..\Python\bin\python.exe" "%QM_ROOT%quota_manager.py" exec --provider openai --policy "%QM_ROOT%companies\%QM_COMPANY%\policy.json" --state "%QM_ROOT%companies\%QM_COMPANY%\state.json" -- %*
exit /b %ERRORLEVEL%
