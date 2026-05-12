# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.

# Script de publication de l'image Docker vers le registry

Write-Host "=== Publication Docker Image - Hydro Forecast API ===" -ForegroundColor Cyan

$registryImage = "{YOUR_REGISTRY}/hydro-forecast-ouysse:latest"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildContext = Join-Path (Split-Path -Parent $scriptDir) "hydro_forecast_api"

# 1. Build de l'image
Write-Host "`n[1/2] Build de l'image Docker..." -ForegroundColor Yellow
Write-Host "  Context: $buildContext" -ForegroundColor Gray
Write-Host "  Tag: $registryImage" -ForegroundColor Gray

docker build -t $registryImage "$buildContext"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Erreur lors du build" -ForegroundColor Red
    exit 1
}

Write-Host "Image buildee avec succes" -ForegroundColor Green

# 2. Push vers le registry
Write-Host "`n[2/2] Push vers le registry..." -ForegroundColor Yellow
Write-Host "  Image: $registryImage" -ForegroundColor Gray

docker push $registryImage

if ($LASTEXITCODE -ne 0) {
    Write-Host "Erreur lors du push" -ForegroundColor Red
    exit 1
}

Write-Host "Image publiee avec succes" -ForegroundColor Green

# Resume
Write-Host "`n=== Publication terminee ===" -ForegroundColor Cyan
Write-Host "Image disponible: $registryImage" -ForegroundColor White
Write-Host "`nPour deployer sur un serveur:" -ForegroundColor White
Write-Host "  docker pull $registryImage" -ForegroundColor Gray
Write-Host "  docker compose up -d" -ForegroundColor Gray
