@echo off
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%\src"
pushd "%REPO%" || exit /b 1
python -m unittest discover -s tests
set "TEST_EXIT=%ERRORLEVEL%"
popd
exit /b %TEST_EXIT%
