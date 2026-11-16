# Start weebot backend and web UI, each in its own PowerShell window.
# Also starts Obscura (https://github.com/h4ckf0r0day/obscura) when WEEBOT_BROWSER_CDP_URL points
# at a local port nothing listens on. Override the binary with OBSCURA_BIN.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

function Start-Obscura {
    $cdp = $env:WEEBOT_BROWSER_CDP_URL
    $envFile = Join-Path $root ".env"
    if (-not $cdp -and (Test-Path $envFile)) {
        $line = Select-String -Path $envFile -Pattern '^\s*WEEBOT_BROWSER_CDP_URL\s*=\s*(.+?)\s*$' | Select-Object -First 1
        if ($line) { $cdp = $line.Matches[0].Groups[1].Value.Trim('"', "'") }
    }
    if (-not $cdp) { return }  # no CDP browser configured: weebot launches Chromium itself

    $uri = $null
    if (-not [Uri]::TryCreate($cdp, [UriKind]::Absolute, [ref]$uri) -or $uri.Port -le 0) {
        Write-Warning "Obscura not started: cannot parse WEEBOT_BROWSER_CDP_URL"
        return
    }
    if ($uri.Host -notin '127.0.0.1', 'localhost', '[::1]') { return }  # remote browser, not ours to start

    $listening = $false
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', $uri.Port); $listening = $true } catch { } finally { $client.Close() }
    if ($listening) { Write-Host "CDP browser already listening on port $($uri.Port)"; return }

    $bin = $env:OBSCURA_BIN
    if (-not $bin) {
        $cmd = Get-Command obscura -ErrorAction SilentlyContinue
        if ($cmd) { $bin = $cmd.Source } else { $bin = Join-Path $env:LOCALAPPDATA "Programs\obscura\obscura.exe" }
    }
    if (-not (Test-Path $bin)) {
        Write-Warning "Obscura not started: $bin not found (install from github.com/h4ckf0r0day/obscura/releases or set OBSCURA_BIN)"
        return
    }

    Start-Process $bin -ArgumentList 'serve', '--port', $uri.Port
    for ($i = 0; $i -lt 20; $i++) {  # up to ~10 s for V8 to come up
        Start-Sleep -Milliseconds 500
        $c = New-Object System.Net.Sockets.TcpClient
        try { $c.Connect('127.0.0.1', $uri.Port); Write-Host "Obscura listening on port $($uri.Port)"; return } catch { } finally { $c.Close() }
    }
    Write-Warning "Obscura started but port $($uri.Port) is not answering yet"
}

Start-Obscura

Start-Process powershell -WorkingDirectory $root -ArgumentList '-NoExit', '-Command', "& '$py' -m weebot.interfaces.web.main"
Start-Process powershell -WorkingDirectory (Join-Path $root "weebot-ui") -ArgumentList '-NoExit', '-Command', 'npm run dev'

Write-Host "Backend starting. Web UI: http://localhost:3000"
