@echo off
setlocal
set "MINI_ROOT=%~dp0"
if not defined PYTHONIOENCODING set "PYTHONIOENCODING=utf-8"

pushd "%MINI_ROOT%" >nul || (
  echo Unable to open Mini Agent project: "%MINI_ROOT%" 1>&2
  exit /b 2
)

if defined MINI_MODEL_FACTORY (
  python -m mini_agent --workspace "%MINI_ROOT%workspace" --model-factory "%MINI_MODEL_FACTORY%" %*
) else if exist "%MINI_ROOT%config.json" (
  python -m mini_agent --workspace "%MINI_ROOT%workspace" --model-factory "mini_agent.openai_compatible:create_model" %*
) else if defined MINI_MODEL (
  python -m mini_agent --workspace "%MINI_ROOT%workspace" --model-factory "mini_agent.openai_compatible:create_model" %*
) else if defined OPENAI_MODEL (
  python -m mini_agent --workspace "%MINI_ROOT%workspace" --model-factory "mini_agent.openai_compatible:create_model" %*
) else (
  python -m mini_agent --workspace "%MINI_ROOT%workspace" --script "%MINI_ROOT%examples\demo_script.json" %*
)

set "MINI_EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %MINI_EXIT_CODE%
