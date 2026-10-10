@echo off
setlocal
set "MINI_ROOT=%~dp0"

pushd "%MINI_ROOT%" >nul || (
  echo Unable to open Mini Agent project: "%MINI_ROOT%" 1>&2
  exit /b 2
)

if defined MINI_MODEL_FACTORY (
  python -m mini_agent --workspace "%MINI_ROOT%workspace" --model-factory "%MINI_MODEL_FACTORY%" %*
) else (
  python -m mini_agent --workspace "%MINI_ROOT%workspace" --script "%MINI_ROOT%examples\demo_script.json" %*
)

set "MINI_EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %MINI_EXIT_CODE%
