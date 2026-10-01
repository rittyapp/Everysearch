# Everysearch release: build -> commit -> push -> GitHub Release (+ Everysearch.exe, version.txt)
# UTF-8 with BOM. Called from release.bat. Log: script\release.log
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $Root
$Log = Join-Path $env:TEMP "everysearch-release.log"
$LogCopy = Join-Path $ScriptDir "release.log"
"" | Set-Content -LiteralPath $Log -Encoding UTF8
function G { $ErrorActionPreference = "Continue"; & git @args 2>&1 | ForEach-Object { "$_" } }
function L($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $m
    Write-Host $line
    for ($k = 0; $k -lt 5; $k++) { try { Add-Content -LiteralPath $Log -Value $line -Encoding UTF8 -ErrorAction Stop; break } catch { Start-Sleep -Milliseconds 300 } }
}
function CopyLog { for ($k = 0; $k -lt 10; $k++) { try { Copy-Item -LiteralPath $Log -Destination $LogCopy -Force -ErrorAction Stop; break } catch { Start-Sleep -Milliseconds 500 } } }

try {
    $Repo = "rittyapp/Everysearch"
    $Version = (Get-Content -LiteralPath (Join-Path $Root "version.txt") -TotalCount 1).Trim()
    $Tag = "v$Version"
    L "=== Everysearch release $Tag ==="

    # 1) build
    L "[1/4] build"
    cmd /c "call `"$Root\script\build_exe2.bat`" < nul" | Out-Null
    $Exe = Join-Path $Root "dist\Everysearch.exe"
    $DistVer = Join-Path $Root "dist\version.txt"
    if (-not (Test-Path -LiteralPath $Exe)) { throw "dist\Everysearch.exe がありません" }
    if ((Get-Item -LiteralPath $Exe).LastWriteTime -lt (Get-Date).AddMinutes(-15)) { throw "EXE が更新されていません（ビルド失敗の可能性）" }
    if ((Get-Content -LiteralPath $DistVer -TotalCount 1).Trim() -ne $Version) { throw "dist\version.txt が $Version ではありません" }
    L ("  OK {0:N0} bytes" -f (Get-Item -LiteralPath $Exe).Length)

    # 2) commit + push
    L "[2/4] commit + push"
    $env:GIT_TERMINAL_PROMPT = "0"
    $MsgFile = Join-Path $ScriptDir "release-msg.txt"
    if (Test-Path -LiteralPath $MsgFile) {
        G add -u | Out-Null
        G add -- doc/lan-wifi-connection.md doc/everything-http-tool.ps1 doc/everything-http-tool.bat doc/everything-http-remote-check.bat script/release.ps1 script/release.bat | Out-Null
        G commit -F $MsgFile | ForEach-Object { L "  $_" }
        if ($LASTEXITCODE -ne 0) { throw "git commit 失敗" }
        Remove-Item -LiteralPath $MsgFile
    }
    G push origin main | ForEach-Object { L "  $_" }
    if ($LASTEXITCODE -ne 0) { throw "git push 失敗" }

    # 3) token from git credential manager
    L "[3/4] GitHub token"
    $ErrorActionPreference = "Continue"; $cred = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null; $ErrorActionPreference = "Stop"
    $Token = ($cred | Where-Object { $_ -like "password=*" } | Select-Object -First 1) -replace "^password=", ""
    if (-not $Token) { throw "GitHub の資格情報が取得できません（git credential fill）" }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $H = @{ Authorization = "Bearer $Token"; Accept = "application/vnd.github+json"; "User-Agent" = "Everysearch-release"; "X-GitHub-Api-Version" = "2022-11-28" }

    # 4) release + assets
    L "[4/4] release $Tag"
    $NotesFile = Join-Path $ScriptDir "release-notes.md"
    $Notes = if (Test-Path -LiteralPath $NotesFile) { [IO.File]::ReadAllText($NotesFile, [Text.Encoding]::UTF8) } else { "" }
    $rel = $null
    try { $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/$Tag" -Headers $H -Method Get; L "  既存リリースを使用" } catch { }
    if (-not $rel) {
        $body = @{ tag_name = $Tag; target_commitish = "main"; name = "Everysearch $Version"; body = $Notes; draft = $false; prerelease = $false } | ConvertTo-Json
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases" -Headers $H -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
    }
    foreach ($f in @($Exe, $DistVer)) {
        $name = Split-Path -Leaf $f
        foreach ($a in @($rel.assets)) { if ($a -and $a.name -eq $name) { Invoke-RestMethod -Uri $a.url -Headers $H -Method Delete | Out-Null } }
        $up = "https://uploads.github.com/repos/$Repo/releases/$($rel.id)/assets?name=$name"
        $r = Invoke-RestMethod -Uri $up -Headers $H -Method Post -ContentType "application/octet-stream" -InFile $f
        L "  uploaded $($r.name) ($($r.size) bytes)"
    }
    L "RELEASE OK: $($rel.html_url)"
    CopyLog
}
catch {
    L "ERROR: $($_.Exception.Message)"
    try { $r = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream()); L ("  " + $r.ReadToEnd()) } catch { }
    CopyLog
    exit 1
}
