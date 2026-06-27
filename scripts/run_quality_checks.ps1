param(
    [switch]$SkipRuff,
    [switch]$SkipPreCommit
)

$ErrorActionPreference = "Stop"

$argsList = @("scripts/run_quality_checks.py")
if ($SkipRuff) {
    $argsList += "--skip-ruff"
}
if ($SkipPreCommit) {
    $argsList += "--skip-pre-commit"
}

python @argsList
