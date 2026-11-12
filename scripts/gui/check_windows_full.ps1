param([Parameter(Mandatory=$true)][string]$Installer)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ((Get-Process -Id $PID).SessionId -eq 0) {
    throw 'Run this check in a signed-in Windows desktop session'
}
$uninstallKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
if (Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like '*loushang*' }) {
    throw 'Use a Windows account with no registered Loushang installation'
}
$root = Join-Path $env:TEMP ("loushang-full-test-" + [guid]::NewGuid().ToString('N'))
$install = Join-Path $root 'installed'
$env:LOUSHANG_HOME = Join-Path $root 'home'
$env:Path = "$install;$env:SystemRoot\System32;$env:SystemRoot"
Remove-Item Env:VIRTUAL_ENV,Env:PYTHONPATH,Env:PYTHONHOME -ErrorAction SilentlyContinue
New-Item -ItemType Directory $env:LOUSHANG_HOME -Force | Out-Null
$env:LOUSHANG_APP_RECORD_ROOT = $null
'{"web":{"port":0,"manageLocal":true}}' |
    Set-Content (Join-Path $env:LOUSHANG_HOME 'host.json') -Encoding Ascii
$endpoint = Join-Path $env:LOUSHANG_HOME 'state/web/endpoint.json'
$mux = Join-Path $install 'loushang-mux.exe'
$gui = $null
$web = $null
$hostStarted = $false

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

try {
    $setup = Start-Process (Resolve-Path $Installer).Path -ArgumentList "/S /D=$install" -Wait -PassThru
    if ($setup.ExitCode) { throw "Installer exited with $($setup.ExitCode)" }
    foreach ($file in @('loushang-gui.exe','loushang.exe','loushang-web.exe','loushang-mux.exe',
            'runtime/python.exe','web/index.html','VCRUNTIME140.dll')) {
        if (-not (Test-Path (Join-Path $install $file))) { throw "Missing installed file $file" }
    }
    "PASS installed GUI, TUI, Web, Mux, Python, Web assets and VC runtime into $install"
    Set-Location $root
    loushang --version
    if ($LASTEXITCODE) { throw 'Installed TUI command failed' }

    if ((Invoke-Mux status).state -ne 'not_running') { throw 'Expected AppHost to start stopped' }
    $gui = Start-Process (Join-Path $install 'loushang-gui.exe') -PassThru
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        $gui.Refresh()
        if ($gui.HasExited) { throw "GUI exited with $($gui.ExitCode)" }
        if ($gui.MainWindowHandle -ne 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($gui.MainWindowHandle -eq 0) { throw 'GUI window did not open' }
    'PASS GUI opened before starting AppHost'

    $first = Invoke-Mux start
    $hostStarted = $true
    if ($first.state -ne 'running') { throw 'AppHost did not start' }
    $second = Invoke-Mux restart
    if ($second.state -ne 'running' -or $second.instanceId -eq $first.instanceId) {
        throw 'AppHost did not restart into a new instance'
    }
    'PASS AppHost start and restart'
    $web = Start-Process (Join-Path $install 'loushang-web.exe') -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $root 'web.out') -RedirectStandardError (Join-Path $root 'web.err')
    for ($attempt=0; $attempt -lt 40 -and -not (Test-Path $endpoint); $attempt++) {
        if ($web.HasExited) { throw (Get-Content (Join-Path $root 'web.err') -Raw) }
        Start-Sleep -Milliseconds 250
    }
    $url = (Get-Content $endpoint -Raw | ConvertFrom-Json).url
    $page = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 15
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch '<html') { throw 'Web did not serve HTML' }
    $connected = (Invoke-Web @{operation='manage';action='connect'}).result
    if ($connected.state -ne 'running' -or $connected.instanceId -ne $second.instanceId) {
        throw "Web failed to connect: $($connected | ConvertTo-Json -Compress)"
    }
    $workspace = (New-Item -ItemType Directory (Join-Path $root 'workspace')).FullName
    Invoke-Web @{operation='workspace';action='register';path=$workspace} | Out-Null
    $listed = (Invoke-Web @{operation='workspace';action='list'}).result
    if ($workspace -notin @($listed.workspaces | ForEach-Object { $_.path })) {
        throw 'Workspace registered through Web was missing from AppHost'
    }
    'PASS Web page, AppHost connection and workspace round trip'
} finally {
    if ($gui -and -not $gui.HasExited) { Stop-Process -Id $gui.Id }
    if ($web -and -not $web.HasExited) {
        if ($url) {
            try { Invoke-Web @{operation='shutdown-adapter'} | Out-Null } catch { Write-Warning $_ }
        }
        if (-not $web.WaitForExit(5000)) { Stop-Process -Id $web.Id }
    }
    if ($hostStarted) {
        $stopped = Invoke-Mux stop
        if (-not $stopped.cleanlyStopped) { throw 'AppHost did not stop cleanly' }
        'PASS AppHost stop'
    }
    $uninstaller = Join-Path $install 'uninstall.exe'
    if (Test-Path $uninstaller) {
        $result = Start-Process $uninstaller -ArgumentList '/S' -Wait -PassThru
        if ($result.ExitCode -or (Test-Path (Join-Path $install 'loushang-gui.exe'))) {
            throw "Uninstall failed: $($result.ExitCode)"
        }
        if (-not (Test-Path (Join-Path $env:LOUSHANG_HOME 'host.json'))) {
            throw 'Uninstaller removed user data'
        }
        'PASS uninstall retained user data'
    }
}
