<# 本机部署入口。默认只校验；Build 不启动；Start 拒绝与现有开发进程共用端口/数据。 #>
[CmdletBinding()]
param(
    [ValidateSet('Validate', 'Build', 'Start', 'Stop', 'Status', 'Logs')]
    [string]$Action = 'Validate'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$compose = Join-Path $PSScriptRoot 'compose.local.yaml'
function Invoke-Docker {
    param([string[]]$DockerArguments)
    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) { throw "Docker 操作失败，退出码 $LASTEXITCODE。" }
}
Push-Location $root
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '未安装 Docker CLI。' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env.local'))) {
        if ($Action -in @('Stop', 'Status', 'Logs')) { throw '缺少 docker/.env.local。' }
        $python = Join-Path $root 'backend/.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $python)) { throw '缺少已安装项目依赖的后端 Python 环境。' }
        & $python -X utf8 (Join-Path $PSScriptRoot 'prepare_local_env.py')
        if ($LASTEXITCODE -ne 0) { throw '生成本机 Docker 配置失败。' }
    }
    Invoke-Docker -DockerArguments @('compose', '-f', $compose, 'config', '--quiet')
    switch ($Action) {
        'Validate' { Write-Host 'Compose 校验通过；没有启动服务或修改数据库。' }
        'Build' { Invoke-Docker -DockerArguments @('compose', '-f', $compose, 'build') }
        'Start' {
            $running = & docker compose -f $compose ps --status running -q
            if ($LASTEXITCODE -ne 0) { throw '无法查询现有容器，请先启动 Docker Desktop。' }
            if ($running) { throw '本项目已有容器运行，请使用 Status / Logs 查看，或 Stop 后重新启动。' }
            $watchData = Join-Path (Split-Path $root -Parent) 'Sanas Watch/data'
            if (-not (Test-Path -LiteralPath (Join-Path $watchData 'kuma.db') -PathType Leaf)) {
                throw '未找到已有 Watch SQLite 数据库；拒绝自动创建新的监控数据库。'
            }
            $dbConfig = Get-Content -Raw -LiteralPath (Join-Path $watchData 'db-config.json') | ConvertFrom-Json
            if ($dbConfig.type -ne 'sqlite') { throw '此本机配置只支持已经准备好的 Watch SQLite 数据库。' }
            $occupied = Get-NetTCPConnection -State Listen -LocalPort 8001,3000,3001,8080 -ErrorAction SilentlyContinue
            if ($occupied) {
                $ports = ($occupied.LocalPort | Sort-Object -Unique) -join ', '
                throw "端口 $ports 已被使用。请先明确停止对应服务；禁止同时运行两个 Watch 进程写入同一 data 目录。"
            }
            Invoke-Docker -DockerArguments @('compose', '-f', $compose, 'up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '180')
        }
        'Stop' { Invoke-Docker -DockerArguments @('compose', '-f', $compose, 'down', '--timeout', '60') }
        'Status' { Invoke-Docker -DockerArguments @('compose', '-f', $compose, 'ps') }
        'Logs' { Invoke-Docker -DockerArguments @('compose', '-f', $compose, 'logs', '--tail', '100') }
    }
} finally {
    Pop-Location
}
