# Instalacion completa del Auditor de DIPs en una PC con Windows 10/11.
#
#   1. Python 3.11+ (lo instala con winget, o desde python.org si no hay winget)
#   2. Entorno virtual .venv con las librerias de requirements.txt
#   3. Microsoft Edge (para leer ICAM) y tabla de referencias
#   4. Pruebas automaticas
#
# Uso (normalmente mediante setup.bat):
#   setup.bat                  instalacion completa
#   setup.bat -SinPruebas      no corre las pruebas al final
#
# Se puede ejecutar varias veces: lo que ya esta instalado se omite.

param(
    [switch]$SinPruebas
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # acelera Invoke-WebRequest
$Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Raiz

$PythonMinimo = [Version]"3.11"
$PythonWinget = "Python.Python.3.12"
$PythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

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

# 3. Edge y archivos de datos ----------------------------------------------
Paso "Microsoft Edge (lectura de ICAM)"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
          "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) { Ok "Edge encontrado" }
else { Aviso "No se encontro Microsoft Edge: sin Edge no se puede leer ICAM (use --sin-icam)." }

Paso "Tabla de referencias"
if (Test-Path (Join-Path $Raiz "DIPs References.xlsx")) {
    Ok "DIPs References.xlsx encontrado"
} else {
    Aviso "Falta 'DIPs References.xlsx' en la carpeta del proyecto. Copielo antes de auditar."
}

# 4. Pruebas ---------------------------------------------------------------
if (-not $SinPruebas) {
    Paso "Pruebas automaticas"
    & $venvPy -m pytest
    if ($LASTEXITCODE -ne 0) { Aviso "Algunas pruebas fallaron. Revise el detalle arriba." }
    else { Ok "Todas las pruebas pasaron" }
}

Write-Host ""
Write-Host "Instalacion terminada." -ForegroundColor Green
Write-Host "Para auditar:"
Write-Host "    Arrastre el Excel de entrada sobre auditar.bat. Si se lo pide, inicie sesion"
Write-Host "    en ICAM en la ventana de Edge que se abre y dejela abierta."
