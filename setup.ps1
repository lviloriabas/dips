# Instalacion completa del Auditor de DIPs en una PC con Windows 10/11.
#
#   1. CPython 3.12 x64 (lo instala desde python.org solo para el usuario)
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

$PythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

function Paso($texto) { Write-Host ""; Write-Host "==> $texto" -ForegroundColor Cyan }
function Ok($texto) { Write-Host "    [OK] $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    [!] $texto" -ForegroundColor Yellow }
function Falla($texto) { Write-Host ""; Write-Host "[ERROR] $texto" -ForegroundColor Red; exit 1 }

function Descargar($url, $destino) {
    Write-Host "    Descargando $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing
}

# Se usa una version con paquetes precompilados para Windows x64. No se acepta
# cualquier Python mas nuevo, de 32 bits, ARM64 o con el GIL deshabilitado.
function Python-Compatible($exe) {
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { return $false }
    try {
        & $exe -I -c "import sys, struct, platform; sys.exit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8 and platform.machine().lower() in ('amd64', 'x86_64') else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# Devuelve la ruta real, sin depender del alias de Microsoft Store ni del PATH.
function Buscar-Python {
    $candidatos = @((Join-Path $Raiz ".venv\Scripts\python.exe"),
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe")
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $ruta = & py -3.12 -I -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ruta) { $candidatos += $ruta.Trim() }
        } catch { }
    }
    $candidatos += @(Get-Command python.exe -All -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\*' } |
        ForEach-Object { $_.Source })
    foreach ($exe in ($candidatos | Select-Object -Unique)) {
        if (Python-Compatible $exe) { return $exe }
    }
    return $null
}

# --------------------------------------------------------------------------
Write-Host "Auditor de DIPs - instalacion" -ForegroundColor White
Write-Host "Carpeta: $Raiz"

# 1. Python ---------------------------------------------------------------
Paso "CPython 3.12 de 64 bits (x64), sin permisos de administrador"
$py = Buscar-Python
if (-not $py) {
    $instalador = Join-Path $env:TEMP ("dips-python-" + [guid]::NewGuid().ToString('N') + ".exe")
    try {
        Descargar $PythonUrl $instalador
        Write-Host "    Instalando Python (solo para este usuario)..."
        $destinoPython = 'TargetDir="' + "$env:LOCALAPPDATA\Programs\Python\Python312" + '"'
        $proceso = Start-Process -FilePath $instalador -Wait -PassThru -WindowStyle Hidden -ArgumentList `
            "/quiet", "InstallAllUsers=0", "InstallLauncherAllUsers=0", "Include_launcher=0", `
            "PrependPath=0", "Include_test=0", $destinoPython
        if ($proceso.ExitCode -notin @(0, 3010)) {
            Falla "El instalador de Python termino con codigo $($proceso.ExitCode). Instale Python 3.12 x64 solo para su usuario y vuelva a ejecutar setup.bat."
        }
    } finally {
        Remove-Item -LiteralPath $instalador -ErrorAction SilentlyContinue
    }
    $py = Buscar-Python
    if (-not $py) { Falla "No se encontro Python 3.12 x64 despues de instalarlo. Vuelva a ejecutar setup.bat." }
}
$version = & $py -I -c "import sys; print(sys.version.split()[0])"
Ok "Python $version ($py)"

# 2. Entorno virtual y librerias -------------------------------------------
Paso "Entorno virtual (.venv) y librerias de requirements.txt"
$venvPy = Join-Path $Raiz ".venv\Scripts\python.exe"
if ((Test-Path -LiteralPath (Join-Path $Raiz '.venv')) -and -not (Python-Compatible $venvPy)) {
    $respaldo = Join-Path $Raiz (".venv-incompatible-" + [guid]::NewGuid().ToString('N'))
    Move-Item -LiteralPath (Join-Path $Raiz '.venv') -Destination $respaldo
    Aviso "El entorno anterior no era compatible. Se conservo en $respaldo"
}
if (-not (Test-Path $venvPy)) {
    & $py -I -m venv .venv
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo crear el entorno virtual." }
    Ok "Entorno virtual creado"
} else {
    Ok "El entorno virtual ya existe"
}
& $venvPy -I -m pip --isolated install --upgrade pip --only-binary=:all: --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Falla "No se pudo actualizar pip. Revise la conexion a internet o el proxy y vuelva a ejecutar setup.bat." }
& $venvPy -I -m pip --isolated install -r requirements.txt --only-binary=:all: --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Falla "No se pudieron descargar las librerias precompiladas para Python 3.12 x64. Revise la conexion a internet o el proxy y vuelva a ejecutar setup.bat. No se necesitan Build Tools de Visual C++." }
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
    if ($LASTEXITCODE -ne 0) { Falla "Algunas pruebas fallaron. Revise el detalle arriba." }
    else { Ok "Todas las pruebas pasaron" }
}

Write-Host ""
Write-Host "Instalacion terminada." -ForegroundColor Green
Write-Host "Para auditar:"
Write-Host "    Arrastre el Excel de entrada sobre auditar.bat. Si se lo pide, inicie sesion"
Write-Host "    en ICAM en la ventana de Edge que se abre y dejela abierta."
