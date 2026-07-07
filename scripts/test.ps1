$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $repo "src"
python -m unittest discover -s tests
