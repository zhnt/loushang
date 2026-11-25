param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [string]$TestParent = $env:TEMP,
    [string]$Version,
    [string]$Commit,
    [string]$Evidence
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$desktop = (Get-Process -Id $PID).SessionId -ne 0 -and [Environment]::UserInteractive
$Installer = (Resolve-Path $Installer).Path
$msi = [IO.Path]::GetExtension($Installer) -eq '.msi'
$format = if ($msi) { 'MSI' } else { 'NSIS' }
if ($Evidence) { $Evidence = (Resolve-Path $Evidence).Path }
$checksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash.ToLowerInvariant()
$expected = "$checksum  $([IO.Path]::GetFileName($Installer))"
if ((Get-Content -LiteralPath "$Installer.sha256" -Raw).Trim() -cne $expected) {
    throw 'Installer SHA-256 mismatch'
}
"PASS $format SHA-256"
$uninstallKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
if (Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like '*loushang*' }) {
    throw 'Use a Windows account with no registered Loushang installation'
}
$root = Join-Path (Resolve-Path $TestParent).Path ("ls-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$install = Join-Path $root 'installed'
$env:LOUSHANG_HOME = Join-Path $root 'home'
$env:Path = "$install;$env:SystemRoot\System32;$env:SystemRoot"
Remove-Item Env:VIRTUAL_ENV,Env:PYTHONPATH,Env:PYTHONHOME -ErrorAction SilentlyContinue
New-Item -ItemType Directory $env:LOUSHANG_HOME -Force | Out-Null
Remove-Item Env:LOUSHANG_APP_RECORD_ROOT,Env:LOUSHANG_RUNTIME_DIR,Env:LOUSHANG_TMPDIR `
    -ErrorAction SilentlyContinue
'{"web":{"port":0,"manageLocal":true}}' |
    Set-Content (Join-Path $env:LOUSHANG_HOME 'host.json') -Encoding Ascii
$endpoint = Join-Path $env:LOUSHANG_HOME 'state/web/endpoint.json'
$mux = Join-Path $install 'loushang-mux.exe'
$gui = $null
$web = $null
$hostStarted = $false

function Invoke-Installer([string]$Phase) {
    if ($msi) {
        $operation = if ($Phase -eq 'uninstall') { '/x' } else { '/i' }
        $logRoot = if ($Evidence) { $Evidence } else { $root }
        $log = Join-Path $logRoot "msiexec-$Phase.log"
        $arguments = "$operation `"$Installer`" /qn /norestart /l*v `"$log`""
        if ($Phase -ne 'uninstall') { $arguments += " INSTALLDIR=`"$install`"" }
        if ($Phase -eq 'reinstall') { $arguments += ' REINSTALL=ALL REINSTALLMODE=amus' }
        $process = Start-Process msiexec.exe -ArgumentList $arguments -Wait -PassThru
    } elseif ($Phase -eq 'uninstall') {
        $process = Start-Process (Join-Path $install 'uninstall.exe') -ArgumentList '/S' -Wait -PassThru
    } else {
        $process = Start-Process $Installer -ArgumentList "/S /D=$install" -Wait -PassThru
    }
    if ($process.ExitCode) { throw "$format $Phase exited with $($process.ExitCode)" }
}

function Test-PeMachine([string]$Path) {
    $reader = [IO.BinaryReader]::new([IO.File]::OpenRead($Path))
    try {
        if ($reader.ReadUInt16() -ne 0x5a4d) { throw "Missing PE DOS header: $Path" }
        $reader.BaseStream.Position = 0x3c
        $reader.BaseStream.Position = $reader.ReadUInt32()
        if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne 0x8664) {
            throw "Expected AMD64 PE image: $Path"
        }
    } finally { $reader.Dispose() }
}

function Invoke-Mux([string]$Action) {
    $result = & $mux service $Action --json
    if ($LASTEXITCODE) { throw "AppHost ${Action} failed: $result" }
    $result | ConvertFrom-Json
}

function Invoke-Web([hashtable]$Body) {
    Invoke-RestMethod "$url/api/loushang" -Method Post -TimeoutSec 30 `
        -Headers @{'X-Loushang-Client'='1'} -ContentType 'application/json' `
        -Body ($Body | ConvertTo-Json -Compress)
}

$config = Join-Path $env:LOUSHANG_HOME 'host.json'
$configHash = (Get-FileHash $config).Hash
$workspace = 'default'
$expectedSession = $null
try {
    foreach ($phase in @('clean', 'reinstall')) {
        "Checking $phase installation"
        Invoke-Installer $phase
        foreach ($file in @('loushang-gui.exe','loushang.exe','loushang-web.exe','loushang-mux.exe',
                'runtime/python.exe','VCRUNTIME140.dll')) {
            Test-PeMachine (Join-Path $install $file)
        }
        $required = @('web/index.html','LICENSE','NOTICE')
        if (-not $msi) { $required += 'uninstall.exe' }
        foreach ($file in $required) {
            if (-not (Test-Path (Join-Path $install $file))) { throw "Missing installed file $file" }
        }
        foreach ($file in @('.git','.venv','.loushang','node_modules','src')) {
            if (Test-Path (Join-Path $install $file)) { throw "Unexpected development or user data: $file" }
        }
        $manifest = Get-Content (Join-Path $install 'manifest.json') -Raw | ConvertFrom-Json
        if ($manifest.architecture -ne 'x86_64' -or ($Version -and $manifest.version -ne $Version) -or
            ($Commit -and $manifest.commit -ne $Commit)) {
            throw 'Unexpected installed manifest'
        }
        if ($Version) {
            $registered = @(Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -eq 'loushang-gui' })
            if ($registered.Count -ne 1 -or $registered[0].DisplayVersion -ne $Version) {
                throw "Unexpected $format registered product version"
            }
        }
        if ((Get-FileHash $config).Hash -ne $configHash) { throw 'Configuration changed during install' }
        Set-Location $root
        & (Join-Path $install 'loushang.exe') --version
        if ($LASTEXITCODE) { throw 'Installed TUI command failed' }
        $python = Join-Path $install 'runtime/python.exe'
        & $python -I -c "import loushang.coding, pathlib, struct, sys; assert struct.calcsize('P') == 8; assert pathlib.Path(loushang.coding.__file__).resolve().is_relative_to(pathlib.Path(sys.prefix).resolve())"
        if ($LASTEXITCODE) { throw 'Bundled Python or product code failed to load' }

        if ((Invoke-Mux status).state -ne 'not_running') { throw 'Expected AppHost to start stopped' }
        if ($phase -eq 'reinstall') {
            if ($desktop) {
                $gui = Start-Process (Join-Path $install 'loushang-gui.exe') -PassThru
                for ($attempt=0; $attempt -lt 40; $attempt++) {
                    $gui.Refresh()
                    if ($gui.HasExited) { throw "GUI exited with $($gui.ExitCode)" }
                    if ($gui.MainWindowHandle -ne 0) { break }
                    Start-Sleep -Seconds 1
                }
                if ($gui.MainWindowHandle -eq 0) { throw 'GUI window did not open' }
                'PASS GUI opened before starting AppHost'
                Stop-Process -Id $gui.Id
                if (-not $gui.WaitForExit(10000)) { throw 'GUI did not exit' }
            } else {
                'NOT VERIFIED: Windows runner has no interactive desktop session'
            }
        }

        $hostStarted = $true
        $hostStatus = Invoke-Mux start
        if ($hostStatus.state -ne 'running') { throw "AppHost did not start: $($hostStatus | ConvertTo-Json -Compress)" }
        'PASS AppHost start'
        Remove-Item $endpoint -ErrorAction SilentlyContinue
        $url = $null
        $logRoot = if ($Evidence) { $Evidence } else { $root }
        $web = Start-Process (Join-Path $install 'loushang-web.exe') -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logRoot "web-$phase.out") `
            -RedirectStandardError (Join-Path $logRoot "web-$phase.err")
        for ($attempt=0; $attempt -lt 80 -and -not (Test-Path $endpoint); $attempt++) {
            if ($web.HasExited) { throw (Get-Content (Join-Path $logRoot "web-$phase.err") -Raw) }
            Start-Sleep -Milliseconds 250
        }
        $url = (Get-Content $endpoint -Raw | ConvertFrom-Json).url
        $page = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 15
        if ($page.StatusCode -ne 200 -or $page.Content -notmatch '<html') { throw 'Web did not serve HTML' }
        $connected = (Invoke-Web @{operation='manage';action='connect'}).result
        if ($connected.state -ne 'running' -or $connected.instanceId -ne $hostStatus.instanceId) {
            throw "Web failed to connect: $($connected | ConvertTo-Json -Compress)"
        }
        'PASS Web served HTML and connected to AppHost'
        if ($phase -eq 'clean') {
            $created = (Invoke-Web @{operation='workspace';action='create-chat';path=$workspace;
                title='Installer acceptance Session'}).result
            if (-not $created.sessionId) { throw 'Installed AppHost failed to create a Session' }
        }
        $viewId = [guid]::NewGuid().ToString()
        $snapshot = (Invoke-Web @{operation='live';action='snapshot';viewId=$viewId;workspace=$workspace}).result
        $session = $snapshot.sessions[0].executions.identity | ConvertTo-Json -Compress
        if (-not $snapshot.sessions[0].executions.identity) { throw 'Installed AppHost returned no Session' }
        Invoke-Web @{operation='live';action='close';viewId=$viewId;workspace=$workspace} | Out-Null
        if ($phase -eq 'clean') { $expectedSession = $session }
        elseif ($session -cne $expectedSession) { throw 'Session identity changed after reinstall' }
        Invoke-Web @{operation='shutdown-adapter'} | Out-Null
        if (-not $web.WaitForExit(15000) -or $web.ExitCode) { throw 'Web did not stop cleanly' }
        'PASS Web shutdown'
        $stopped = Invoke-Mux stop
        if ($stopped.state -ne 'not_running' -or -not $stopped.cleanlyStopped) {
            throw 'AppHost did not stop cleanly'
        }
        $hostStarted = $false
        "PASS $phase install, AppHost connection, Session and clean stop"
        if ($phase -eq 'clean') { Remove-Item (Join-Path $install 'web/index.html') }
    }
} catch {
    Write-Warning "Installation verification failed: $_"
    throw
} finally {
    if ($gui -and -not $gui.HasExited) { Stop-Process -Id $gui.Id }
    if ($web -and -not $web.HasExited) {
        if ($url) {
            try { Invoke-Web @{operation='shutdown-adapter'} | Out-Null } catch { Write-Warning $_ }
        }
        if (-not $web.WaitForExit(5000)) { Stop-Process -Id $web.Id }
    }
    if ($hostStarted) {
        try {
            $stopped = Invoke-Mux stop
            if (-not $stopped.cleanlyStopped) { throw 'AppHost did not stop cleanly' }
            'PASS AppHost stop during cleanup'
        } catch {
            Write-Warning "AppHost cleanup failed: $_"
        }
    }
    if ($Evidence) {
        Get-ChildItem -LiteralPath $env:LOUSHANG_HOME -Recurse -File -Filter 'lifecycle-*.jsonl' |
            Copy-Item -Destination $Evidence
    }
    $installed = @(Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq 'loushang-gui' })
    if ($installed.Count) {
        Invoke-Installer uninstall
        if ((Test-Path (Join-Path $install 'loushang-gui.exe')) -or
            (Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -eq 'loushang-gui' })) {
            throw "$format uninstall left installed product files or registration"
        }
        if ((Get-FileHash $config).Hash -ne $configHash -or -not (Test-Path (Join-Path $env:LOUSHANG_HOME 'data'))) {
            throw 'Uninstaller removed user data'
        }
        'PASS uninstall retained user data'
    }
}
