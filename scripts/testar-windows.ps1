# Valida o Jarvis no Windows: suíte, diagnóstico, benchmark e comandos novos.
# Uso, na pasta do repositório: .\scripts\testar-windows.ps1
# Trava de arquivo, troca com os.replace e taskkill só passam de verdade aqui.
# O benchmark mede um vault sintético. O script não envia e-mail e não lê nota.
# O smoke só classifica frases sintéticas e pede --help. Não atualiza e não exporta.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$Falhas = New-Object System.Collections.Generic.List[string]

$Python = $null
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $Python = $VenvPython
} else {
    foreach ($nome in @("python", "py")) {
        $candidato = Get-Command $nome -ErrorAction SilentlyContinue
        if ($null -ne $candidato) {
            $Python = $candidato.Source
            break
        }
    }
}
if (-not $Python) {
    Write-Host "FALHOU: não encontrei o Python. Instale o Python 3.11 ou mais novo."
    exit 1
}

Write-Host "Python: $Python"
Write-Host ""

Write-Host "== testes =="
# Equivale a: python -m unittest discover -s tests -t .
& $Python -m unittest discover -s tests -t . -v
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("testes")
    Write-Host "FALHOU: testes"
} else {
    Write-Host "PASSOU: testes"
}

Write-Host ""
Write-Host "== diagnóstico =="
# Equivale a: python -m jarvis doctor
& $Python -m jarvis doctor
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("diagnóstico")
    Write-Host "FALHOU: diagnóstico"
} else {
    Write-Host "PASSOU: diagnóstico"
}

Write-Host ""
Write-Host "== benchmark =="
Write-Host "Benchmark sintético. Não usa as suas notas."
# Equivale a: python -m jarvis.benchmark
& $Python -m jarvis.benchmark
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("benchmark")
    Write-Host "FALHOU: benchmark"
} else {
    Write-Host "PASSOU: benchmark"
}

Write-Host ""
Write-Host "== comandos novos =="
# Equivale a: python -m jarvis --versao
& $Python -m jarvis --versao
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("versao")
    Write-Host "FALHOU: versao"
} else {
    Write-Host "PASSOU: versao"
}
# Equivale a: python -m jarvis anki --help
& $Python -m jarvis anki --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("anki")
    Write-Host "FALHOU: anki"
} else {
    Write-Host "PASSOU: anki"
}
# Equivale a: python -m jarvis anki exportar --help
& $Python -m jarvis anki exportar --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("anki exportar")
    Write-Host "FALHOU: anki exportar"
} else {
    Write-Host "PASSOU: anki exportar"
}
# Equivale a: python -m jarvis atualizar --help
& $Python -m jarvis atualizar --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("atualizar")
    Write-Host "FALHOU: atualizar"
} else {
    Write-Host "PASSOU: atualizar"
}
# Equivale a: python -m jarvis relatorio --help
& $Python -m jarvis relatorio --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("relatorio")
    Write-Host "FALHOU: relatorio"
} else {
    Write-Host "PASSOU: relatorio"
}
# Equivale a: python -m jarvis destaques --help
& $Python -m jarvis destaques --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("destaques")
    Write-Host "FALHOU: destaques"
} else {
    Write-Host "PASSOU: destaques"
}
# Equivale a: python -m jarvis video --help
& $Python -m jarvis video --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("video")
    Write-Host "FALHOU: video"
} else {
    Write-Host "PASSOU: video"
}
# Equivale a: python -m jarvis audio --help
& $Python -m jarvis audio --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("audio")
    Write-Host "FALHOU: audio"
} else {
    Write-Host "PASSOU: audio"
}
# Equivale a: python -m jarvis midia --help
& $Python -m jarvis midia --help
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("midia")
    Write-Host "FALHOU: midia"
} else {
    Write-Host "PASSOU: midia"
}

$codigo = @"
from jarvis.comandos import classificar
frases = [
    ("se atualiza", "atualizar"),
    ("conecta ideias", "connect"),
    ("o que minhas notas dizem sobre farol sintetico", "notes_say"),
    ("me lembra algo", "resurface"),
    ("quero aprender farol sintetico", "learn"),
    ("como estou em farol sintetico", "progress"),
    ("me deixa explicar farol sintetico", "feynman"),
    ("me pergunta sobre farol sintetico", "socratic"),
    ("revisao semanal", "weekly"),
    ("quanto estudei essa semana?", "week_stats"),
    ("comeca uma sessao de estudo de 25 minutos sobre farol sintetico", "sessao_iniciar"),
    ("quanto falta?", "sessao_falta"),
    ("encerra a sessao", "sessao_encerrar"),
    ("qual minha sequencia?", "streak"),
    ("exporta meus cartoes", "anki"),
    ("resume esse video https://www.youtube.com/watch?v=Abcdefghijk", "study_video"),
    ("resume esse audio episodio-sintetico.mp3", "study_audio"),
    ("processa minha fila de midia", "media_queue"),
    ("importa destaques do kindle", "destaques"),
    ("pausa", "sessao_pausa"),
    ("continua a sessao", "sessao_continua"),
    ("cancela o lembrete de pagar o boleto", "cancel"),
    ("para a revisao", "review_pause"),
]
for frase, kind in frases:
    achado = classificar(frase).kind
    if achado != kind:
        raise SystemExit(frase + " -> " + achado)
print("comandos ok")
"@
& $Python -c $codigo
if ($LASTEXITCODE -ne 0) {
    $Falhas.Add("classificar")
    Write-Host "FALHOU: classificar"
} else {
    Write-Host "PASSOU: classificar"
}

Write-Host ""
Write-Host "Resumo"
if ($Falhas.Count -eq 0) {
    Write-Host "PASSOU: testes, diagnóstico, benchmark e comandos novos."
    exit 0
}
Write-Host ("FALHOU: " + ($Falhas -join ", ") + ".")
exit 1
