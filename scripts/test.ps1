$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$runtimeScript = Join-Path $PSScriptRoot "use_local_postgres_runtime.ps1"
$testSchema = "test_suite_$PID"
& $runtimeScript -TestMode -TestSchema $testSchema
$env:PYTHONPATH = Join-Path $repo "src"
Push-Location $repo
try {
  python -m unittest discover -s tests
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
finally {
  Pop-Location
  $cleanup = @'
import os
import re

import psycopg

schema = os.environ["DATABASE_SCHEMA"]
if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
    raise SystemExit("invalid test schema")
if os.environ.get("HAWKNETIC_TEST_POSTGRES_SCHEMAS") != "true":
    raise SystemExit("test schema cleanup requires isolated PostgreSQL test mode")
with psycopg.connect(os.environ["DATABASE_MIGRATION_URL"], autocommit=True) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        database_name = str(cursor.fetchone()[0])
        if database_name != "hawknetic_research":
            raise SystemExit("refusing test schema cleanup outside hawknetic_research")
        cursor.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name LIKE 'test\\_%' ESCAPE '\\'"
        )
        for (test_schema,) in cursor.fetchall():
            if not re.fullmatch(r"test_[a-z0-9_]{1,58}", str(test_schema)):
                raise SystemExit("unexpected test schema name")
            cursor.execute(f'DROP SCHEMA IF EXISTS "{test_schema}" CASCADE')
'@
  $cleanup | python -
}
