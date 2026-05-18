# Atajo para commit + push del proyecto FUTVS
# Uso:
#   .\gp.ps1 "mensaje del commit"
#
# Hace en orden: pull --rebase, add ., commit, push
# Si algun paso falla, frena y muestra el error.

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Mensaje
)

$ErrorActionPreference = "Stop"
Set-Location -Path "C:\Users\facun\football-forecast"

Write-Host ""
Write-Host "==> git pull --rebase --autostash" -ForegroundColor Cyan
git pull --rebase --autostash
if ($LASTEXITCODE -ne 0) { Write-Host "Pull fallo." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "==> git add ." -ForegroundColor Cyan
git add .

Write-Host ""
Write-Host "==> git commit -m `"$Mensaje`"" -ForegroundColor Cyan
git commit -m $Mensaje
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nada que commitear o error en commit." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "==> git push" -ForegroundColor Cyan
git push
if ($LASTEXITCODE -ne 0) { Write-Host "Push fallo." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Listo. Cambios pusheados al repo." -ForegroundColor Green
