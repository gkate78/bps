param(
    [Parameter(Position=0)]
    [ValidateSet("setup", "run", "check", "dbview")]
    [string]$Command = "run"
)

$ErrorActionPreference = "Stop"

function Use-Venv {
    if (Test-Path ".venv\Scripts\Activate.ps1") {
        . ".venv\Scripts\Activate.ps1"
    }
}

switch ($Command) {
    "setup" {
        if (-not (Test-Path ".venv")) {
            python -m venv .venv
        }
        Use-Venv
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        Write-Host "Setup complete."
    }
    "run" {
        Use-Venv
        uvicorn main:app --reload
    }
    "check" {
        Use-Venv
        $syntaxCheck = @'
import ast
import pathlib
import sys

roots = [pathlib.Path("main.py"), pathlib.Path("app"), pathlib.Path("scripts")]
files = []
for root in roots:
    if not root.exists():
        continue
    if root.is_dir():
        files.extend(p for p in root.rglob("*.py") if "venv" not in p.parts and ".venv" not in p.parts)
    else:
        files.append(root)

errors = []
for path in files:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append((str(path), str(exc)))

if errors:
    print("Syntax check failed:")
    for path, err in errors:
        print(f"- {path}: {err}")
    sys.exit(1)

print(f"Syntax check complete ({len(files)} files).")
'@
        $tmp = New-TemporaryFile
        try {
            Set-Content -Path $tmp -Value $syntaxCheck -NoNewline
            python $tmp
        }
        finally {
            Remove-Item $tmp -ErrorAction SilentlyContinue
        }
    }
    "dbview" {
        Use-Venv
        python scripts/db_view.py
    }
}
