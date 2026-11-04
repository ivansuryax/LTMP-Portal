$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install and start Docker Desktop first.' }
if (-not (Test-Path '.env')) {
  docker volume inspect ltmp-modern_pgdata *> $null
  if ($LASTEXITCODE -eq 0) {
    throw 'SAFETY STOP: Existing database found but .env is missing. Restore the previous POSTGRES_PASSWORD. Do not delete volumes.'
  }
  $chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
  $buffer = [byte[]]::new(48)
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
  $password = -join ($buffer | ForEach-Object { $chars[$_ % $chars.Length] })
  [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'), "POSTGRES_PASSWORD=$password`nCOOKIE_SECURE=false`n", (New-Object System.Text.UTF8Encoding($false)))
  Write-Host 'Created .env for a NEW local installation. Keep it safe.'
}
if (-not (Test-Path 'imports/LTMP.xlsx')) { throw 'Missing imports/LTMP.xlsx' }
docker compose -p ltmp-modern config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid Docker Compose configuration' }
docker compose -p ltmp-modern up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed; inspect logs' }
Write-Host 'Open http://localhost:5173 after API is healthy.'
Write-Host 'Health: curl -i http://localhost:5173/api/health'
Write-Host 'Do not run docker compose down -v.'
