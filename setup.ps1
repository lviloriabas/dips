# Instalacion completa del Auditor de DIPs en una PC con Windows 10/11.
#
#   1. Python 3.11+ (lo instala con winget, o desde python.org si no hay winget)
#   2. Entorno virtual .venv con las librerias de requirements.txt
#   3. Ollama + modelo local (opcional; solo se usa con la opcion --llm)
#   4. Pruebas automaticas
#
# Uso (normalmente mediante setup.bat):
#   setup.bat                  instalacion completa con el modelo de config.yaml
#   setup.bat -ModeloLiviano   usa ministral-3:3b (para PCs con poca RAM)
#   setup.bat -SinModelo       no instala Ollama ni descarga modelos
#   setup.bat -SinPruebas      no corre las pruebas al final
#
# Se puede ejecutar varias veces: lo que ya esta instalado se omite.

param(
    [switch]$SinModelo,
    [switch]$ModeloLiviano,
    [switch]$SinPruebas,
    [string]$Modelo = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # acelera Invoke-WebRequest
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Raiz

$PythonMinimo = [Version]"3.11"
$PythonWinget = "Python.Python.3.12"
$PythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
$OllamaUrl = "https://ollama.com/download/OllamaSetup.exe"
$ModeloLivianoNombre = "ministral-3:3b"

function Paso($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Ok($texto) { Write-Host "    [OK] $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    [!] $texto" -ForegroundColor Yellow }
function Falla($texto) { Write-Host ""; Write-Host "[ERROR] $texto" -ForegroundColor Red; exit 1 }

function Actualizar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Tiene-Winget { return [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Descargar($url, $destino) {
    Write-Host "    Descargando $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing
}

# Devuelve el comando de un Python >= 3.11 real (ignora el alias de Microsoft Store).
function Buscar-Python {
    $candidatos = @(
        @("py", "-3"),
        @("python"),
        @("$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"),
        @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"),
        @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"),
        @("$env:ProgramFiles\Python312\python.exe")
    )
    foreach ($c in $candidatos) {
        $exe = $c[0]
        $args_ = @($c | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue) -and -not (Test-Path $exe)) { continue }
        try {
            $v = & $exe @args_ -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -and ([Version]$v.Trim() -ge $PythonMinimo)) {
                return [pscustomobject]@{ Exe = $exe; Args = $args_ }
            }
        } catch { }
    }
    return $null
}

# --------------------------------------------------------------------------
Write-Host "Auditor de DIPs - instalacion" -ForegroundColor White
Write-Host "Carpeta: $Raiz"

# 1. Python ---------------------------------------------------------------
Paso "Python $PythonMinimo o superior"
$py = Buscar-Python
if (-not $py) {
    if (Tiene-Winget) {
        Write-Host "    Instalando $PythonWinget con winget..."
        winget install --id $PythonWinget -e --scope user --silent `
            --accept-package-agreements --accept-source-agreements | Out-Host
    } else {
        $instalador = Join-Path $env:TEMP "python-instalador.exe"
        Descargar $PythonUrl $instalador
        Write-Host "    Instalando Python (solo para este usuario)..."
        Start-Process $instalador -Wait -ArgumentList `
            "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_test=0"
        Remove-Item $instalador -ErrorAction SilentlyContinue
    }
    Actualizar-Path
    $py = Buscar-Python
    if (-not $py) { Falla "No se pudo instalar Python. Instalelo desde https://www.python.org y vuelva a ejecutar setup.bat" }
}
$pyExe = $py.Exe; $pyArgs = @($py.Args)
$version = & $pyExe @pyArgs -c "import sys; print(sys.version.split()[0])"
Ok "Python $version ($pyExe)"

# 2. Entorno virtual y librerias -------------------------------------------
Paso "Entorno virtual (.venv) y librerias de requirements.txt"
$venvPy = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo crear el entorno virtual." }
    Ok "Entorno virtual creado"
} else {
    Ok "El entorno virtual ya existe"
}
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $venvPy -m pip install -r requirements.txt --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Falla "No se pudieron instalar las librerias (revise la conexion a internet o el proxy)." }
Ok "Librerias instaladas"

# 3. Archivos de datos -----------------------------------------------------
Paso "Tabla de referencias"
if (Test-Path (Join-Path $Raiz "DIPs References.xlsx")) {
    Ok "DIPs References.xlsx encontrado"
} else {
    Aviso "Falta 'DIPs References.xlsx' en la carpeta del proyecto. Copielo antes de auditar."
}

# 4. Ollama y modelo local -------------------------------------------------
if ($SinModelo) {
    Paso "Modelo local"
    Aviso "Omitido (-SinModelo). La auditoria funciona sin modelo; solo no estara disponible --llm."
} else {
    Paso "Ollama (motor para el modelo local)"
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollama) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
    if (-not (Test-Path $ollama)) {
        if (Tiene-Winget) {
            winget install --id Ollama.Ollama -e --silent `
                --accept-package-agreements --accept-source-agreements | Out-Host
        } else {
            $instalador = Join-Path $env:TEMP "OllamaSetup.exe"
            Descargar $OllamaUrl $instalador
            Start-Process $instalador -Wait -ArgumentList "/VERYSILENT", "/NORESTART"
            Remove-Item $instalador -ErrorAction SilentlyContinue
        }
        Actualizar-Path
        if (-not (Test-Path $ollama)) { $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source }
        if (-not $ollama -or -not (Test-Path $ollama)) { Falla "No se pudo instalar Ollama. Descarguelo de https://ollama.com" }
    }
    Ok "Ollama: $(& $ollama --version)"

    # Servidor de Ollama
    function Ollama-Activo {
        try { Invoke-WebRequest "http://localhost:11434/api/version" -UseBasicParsing -TimeoutSec 3 | Out-Null; return $true }
        catch { return $false }
    }
    if (-not (Ollama-Activo)) {
        Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden
        for ($i = 0; $i -lt 30 -and -not (Ollama-Activo); $i++) { Start-Sleep -Seconds 1 }
        if (-not (Ollama-Activo)) { Falla "El servidor de Ollama no respondio." }
    }
    Ok "Servidor de Ollama activo"

    # Modelo: parametro -Modelo, -ModeloLiviano, o el de config/config.yaml
    if (-not $Modelo) {
        if ($ModeloLiviano) {
            $Modelo = $ModeloLivianoNombre
        } else {
            $Modelo = (& $venvPy -c "import yaml; print(yaml.safe_load(open('config/config.yaml', encoding='utf-8'))['llm']['modelo'])").Trim()
        }
    }
    $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    if ($ramGb -lt 12 -and $Modelo -ne $ModeloLivianoNombre) {
        Aviso "La PC tiene $ramGb GB de RAM. Si va lenta, use: setup.bat -ModeloLiviano"
    }
    Paso "Modelo local: $Modelo (la primera vez descarga varios GB)"
    & $ollama pull $Modelo
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo descargar el modelo $Modelo." }
    if ($Modelo -ne (& $venvPy -c "import yaml; print(yaml.safe_load(open('config/config.yaml', encoding='utf-8'))['llm']['modelo'])").Trim()) {
        Aviso "Para usar $Modelo por defecto, cambie 'llm: modelo:' en config/config.yaml (o use --modelo $Modelo)."
    }
    Ok "Modelo $Modelo listo"
}

# 5. Pruebas ---------------------------------------------------------------
if (-not $SinPruebas) {
    Paso "Pruebas automaticas"
    & $venvPy -m pytest
    if ($LASTEXITCODE -ne 0) { Aviso "Algunas pruebas fallaron. Revise el detalle arriba." }
    else { Ok "Todas las pruebas pasaron" }
}

Write-Host ""
Write-Host "Instalacion terminada." -ForegroundColor Green
Write-Host "Para auditar: arrastre el Excel de entrada sobre auditar.bat, o ejecute:"
Write-Host "    auditar.bat `"ruta\export.xlsx`" [--llm]"
