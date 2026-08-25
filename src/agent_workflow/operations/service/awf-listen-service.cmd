@echo off
rem awf-listen-service.cmd — Windows entry point for the listener service (WinSW).
rem
rem It invokes the same native Python service entry point as macOS/Linux.
rem dispatch.env is parsed as strict data; PowerShell and Git Bash are not used.

setlocal
if "%AWF_PYTHON%"=="" (
  set "AWF_PYTHON=python"
)

"%AWF_PYTHON%" -m agent_workflow.operations.awf_service
exit /b %ERRORLEVEL%
