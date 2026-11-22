param([string]$Python = 'python')
# 直接运行命令行，查看日志，不需要启动服务、网页、模型或网络。
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Push-Location $projectPath
$previousLimit = $env:HISTORY_LIMIT
try {
    $env:HISTORY_LIMIT = '6'
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $a = "A-$suffix"
    $b = "B-$suffix"
    Write-Output "SESSION A=$a; SESSION B=$b"

    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $a --message '登记约束' --direction '模型压缩' --compute GPU --weeks 4 --dataset '公开数据集'
    if ($LASTEXITCODE) { throw 'A write failed' }
    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $a --message '推理延迟'
    if ($LASTEXITCODE) { throw 'A follow-up failed' }
    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $a --message '更正为CPU' --compute CPU
    if ($LASTEXITCODE) { throw 'A correction failed' }
    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $a --message '需要先查找基线'
    if ($LASTEXITCODE) { throw 'A next request failed' }
    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $a --message '继续直到裁剪更正消息'
    if ($LASTEXITCODE) { throw 'A history test failed' }
    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $a --message '再继续一轮'
    if ($LASTEXITCODE) { throw 'A history test failed' }
    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $b --message '新会话不传算力'
    if ($LASTEXITCODE) { throw 'B request failed' }
    & $Python -X utf8 -m backend.cli --data-dir data/cli-check --session $a --message '返回A继续'
    if ($LASTEXITCODE) { throw 'A resume failed' }

    # 从磁盘读文件确认，不只检查打印出来的变量。
    $stateA = Get-Content "data/cli-check/sessions/$a.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $stateB = Get-Content "data/cli-check/sessions/$b.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($stateA.facts.compute -ne 'CPU' -or $stateA.history.Count -ne 6 -or $stateA.messages.Count -ne 14) { throw 'A memory mismatch' }
    if ($null -ne $stateB.facts.compute) { throw 'B inherited A constraint' }
    if ($stateA.trace[0].arguments.facts.compute -ne 'CPU') { throw 'Tool used old constraint' }
    if ($stateA.trace[1].tool -ne 'research_dialogue') { throw 'Dialogue tool did not execute' }
    Write-Output "PASS: A=CPU; recent=6; full=14; B has no compute; switched back to A"
    Write-Output "JSON: data/cli-check/sessions/$a.json and $b.json"
    Write-Output "LOGS: data/cli-check/logs/$a.jsonl and $b.jsonl"
} finally {
    if ($null -eq $previousLimit) { Remove-Item Env:HISTORY_LIMIT -ErrorAction SilentlyContinue }
    else { $env:HISTORY_LIMIT = $previousLimit }
    Pop-Location
}
