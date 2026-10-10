@echo off
setlocal
set "SAFE_ROOT=%~dp0"

pushd "%SAFE_ROOT%" >nul || (
  echo Unable to open Mini Agent project: "%SAFE_ROOT%" 1>&2
  exit /b 2
)

if defined SAFE_MODEL_FACTORY (
  python -m mini_agent --workspace "%SAFE_ROOT%workspace" --model-factory "%SAFE_MODEL_FACTORY%" --approve-writes %*
) else (
  python -m mini_agent --workspace "%SAFE_ROOT%workspace" --script "%SAFE_ROOT%examples\demo_script.json" --approve-writes %*
)

set "SAFE_EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %SAFE_EXIT_CODE%
