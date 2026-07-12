@echo off
rem awf-listen-service.cmd — Windows entry point for the listener service (WinSW).
rem
rem It delegates to the POSIX wrapper (awf-listen-service.sh) via git-bash so the
rem credential-sourcing logic lives in ONE place. git-bash can source dispatch.env
rem (which is stored in POSIX form on Windows); cmd.exe cannot. WinSW's <executable>
rem points at this .cmd; role/repo/tool/model arrive via the environment (WinSW <env>).
rem
rem Requires git-bash. Override its path with AWF_GITBASH if installed elsewhere.

setlocal
if "%AWF_GITBASH%"=="" (
  set "AWF_GITBASH=C:\Program Files\Git\bin\bash.exe"
)

set "SELF_DIR=%~dp0"

rem Hand off to the POSIX wrapper. Double-quote the bash path (has a space) and the
rem script path so cmd passes each as one token; bash then does the real work.
"%AWF_GITBASH%" "%SELF_DIR%awf-listen-service.sh"
exit /b %ERRORLEVEL%
