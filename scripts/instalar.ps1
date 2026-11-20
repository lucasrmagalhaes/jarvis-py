# Instalação do Jarvis no Windows.
# Uso: .\scripts\instalar.ps1 [-Wake]
param(
    [switch]$Wake
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

function Assert-Exit([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

$Python = $null
foreach ($name in @("python", "py")) {
    $candidate = Get-Command $name -ErrorAction SilentlyContinue
    if ($null -ne $candidate) {
        $Python = $candidate.Source
        break
    }
}
if (-not $Python) {
    throw "Não encontrei o Python. Instale o Python 3.11 ou mais novo e tente de novo."
}

if (-not (Test-Path -LiteralPath ".venv")) {
    & $Python -m venv .venv
    Assert-Exit "Não consegui criar o ambiente virtual."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
Assert-Exit "Não consegui atualizar o pip."
& $VenvPython -m pip install -r requirements.txt
Assert-Exit "Não consegui instalar requirements.txt."
if ($Wake) {
    & $VenvPython -m pip install -r requirements-wake-deps.txt
    Assert-Exit "Não consegui instalar requirements-wake-deps.txt."
    & $VenvPython -m pip install --no-deps -r requirements-wake.txt
    Assert-Exit "Não consegui instalar requirements-wake.txt."
}

# Equivale a: python -m jarvis doctor
& $VenvPython -m jarvis doctor
if ($LASTEXITCODE -ne 0) {
    Write-Host "O diagnóstico encontrou pendências. Os próximos passos continuam valendo."
}

Write-Host ""
Write-Host "Próximos passos:"
Write-Host "1. Ative o ambiente: .\.venv\Scripts\Activate.ps1"
Write-Host "2. Se o checklist apontou o vault, rode: python -m jarvis.setup"
Write-Host "3. Faça login no Claude Code uma vez: claude"
Write-Host "4. Converse sem microfone: python -m jarvis.chat"
Write-Host "5. Com microfone: python -m jarvis.main"
Write-Host ""
Write-Host "O arquivo de exemplo das variáveis é .env.example."
Write-Host "Copie para $env:USERPROFILE\.jarvis\.env se quiser editar à mão."
Write-Host "O .env não entra no git."
