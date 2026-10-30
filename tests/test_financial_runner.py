import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows scheduler integration")
class FinancialRunnerTests(unittest.TestCase):
    def test_failed_growth_does_not_stop_dividend_or_relabel_old_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts" / "financial_data.py").write_text("import sys\nif '--needed' in sys.argv: print('yes')\n", encoding="utf-8")
            source = str(ROOT / "scripts" / "update_dashboard_daily.ps1").replace("'", "''")
            python = sys.executable.replace("'", "''")
            script = f"""
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('{source}',[ref]$tokens,[ref]$errors)
$function=$ast.FindAll({{param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-Financials'}},$true)[0]
Invoke-Expression $function.Extent.Text
$Python='{python}'
$script:StepResults=@{{}}
$script:Calls=[System.Collections.Generic.List[string]]::new()
function Write-RunLog([string]$Message) {{}}
function Invoke-Step([string]$Label,[string]$File,[string[]]$Arguments,[int]$TimeoutSeconds) {{
  $script:Calls.Add($Label)
  $script:StepResults[$Label]=$Label -ne 'growth current finance'
}}
Invoke-Financials '2026-10-29'
ConvertTo-Json -InputObject @($script:Calls)
"""
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = json.loads(result.stdout)
            self.assertEqual(calls, ["growth current finance", "dividend quality", "dashboard status"])


if __name__ == "__main__":
    unittest.main()
