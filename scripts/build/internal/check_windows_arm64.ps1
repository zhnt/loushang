param([Parameter(Mandatory=$true)][string]$Evidence)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$failures = [System.Collections.Generic.List[string]]::new()
$target = 'aarch64-pc-windows-msvc'

function Confirm-NativeCommand([string]$Name, [scriptblock]$Command) {
    try {
        & $Command
        if ($LASTEXITCODE) { throw "Command exited with $LASTEXITCODE" }
        "PASS $Name"
    } catch {
        $failures.Add($Name)
        Write-Warning "$Name failed: $_"
    }
}

Confirm-NativeCommand 'ARM64 host and Node' {
    if ($env:RUNNER_ARCH -ne 'ARM64' -or (node -p 'process.arch') -ne 'arm64') {
        throw 'A native Windows ARM64 host and Node are required'
    }
    node --version
}
Confirm-NativeCommand 'ARM64 MSVC linker' {
    $toolchain = "1.98.1-$target"
    rustup toolchain install $toolchain --profile minimal
    if ($LASTEXITCODE) { throw 'Rust toolchain installation failed' }
    $source = Join-Path $Evidence 'native-check.rs'
    'fn main() { assert_eq!(std::env::consts::ARCH, "aarch64"); }' | Set-Content $source -Encoding Ascii
    $exe = Join-Path $Evidence 'native-check.exe'
    rustup run $toolchain rustc $source --target $target -o $exe
    if ($LASTEXITCODE) { throw 'Native link failed' }
    & $exe
    if ($LASTEXITCODE) { throw 'Native Rust program failed' }
    Remove-Item $source,$exe
}

$pythonVersion = (Get-Content .python-version -Raw).Trim()
$python = $null
try {
    uv python install $pythonVersion
    if ($LASTEXITCODE) { throw 'uv could not provision the pinned CPython' }
    $python = uv python find --system --managed-python $pythonVersion
    if ($LASTEXITCODE) { throw 'Pinned managed CPython was not found' }
    & $python -I -c "import pathlib, platform, struct, sys; p=pathlib.Path(sys.executable).read_bytes(); o=struct.unpack_from('<I',p,60)[0]; assert p[o:o+6]==bytes.fromhex('5045000064aa'); print(platform.machine(), sys.version)"
    if ($LASTEXITCODE) { throw 'Installed interpreter does not have an ARM64 PE header' }
    'PASS pinned CPython ARM64 PE'
} catch {
    $python = $null
    $failures.Add('ARM64 CPython')
    Write-Warning "ARM64 CPython failed: $_"
}

if ($python) {
    $venv = Join-Path $env:RUNNER_TEMP 'loushang-arm64-probe'
    uv venv --python $python $venv
    if ($LASTEXITCODE) { throw 'Could not create an isolated ARM64 probe environment' }
    $probePython = Join-Path $venv 'Scripts/python.exe'
    $requirements = Join-Path $env:RUNNER_TEMP 'loushang-requirements-arm64.txt'
    Confirm-NativeCommand 'Locked product wheels' {
        uv --quiet export --locked --no-dev --no-emit-project --output-file $requirements
        if ($LASTEXITCODE) { throw 'Could not export the locked dependencies' }
        uv pip install --dry-run --no-deps --python $probePython --python-platform $target `
            --only-binary :all: --require-hashes -r $requirements
    }
    $pyinstaller = (Select-String -Path scripts/build/internal/common.py -Pattern '^PYINSTALLER = "([^"]+)"').Matches[0].Groups[1].Value
    Confirm-NativeCommand 'PyInstaller wheels' {
        uv pip install --dry-run --python $probePython --python-platform $target --only-binary :all: $pyinstaller
    }
} else {
    'NOT VERIFIED: target interpreter unavailable for native wheel checks'
}

Confirm-NativeCommand 'Tauri ARM64 CLI' {
    npm ci --prefix gui --no-audit --no-fund
    if ($LASTEXITCODE) { throw 'Locked Tauri CLI dependencies did not install' }
    & ./gui/node_modules/.bin/tauri.cmd --version
}
Get-Item "$env:windir\System32\vcruntime140.dll" -ErrorAction SilentlyContinue |
    Select-Object Name,VersionInfo | Out-String
foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    Get-ChildItem -Path "$root\Microsoft\EdgeWebView\Application" -Directory -ErrorAction SilentlyContinue |
        Select-Object Name | Out-String
}
if ($failures.Count) { throw "Windows ARM64 package prerequisites failed: $failures" }
