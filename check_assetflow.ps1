<#
AssetFlow 质量检查。默认只运行不连接数据库的测试，不启动服务、不执行迁移。
-WithMySQL 显式启用现有开发库集成检查；-Build 生成本地地址的前端产物。
示例：.\check_assetflow.ps1 -WithMySQL -Build -ServiceUrl http://127.0.0.1:8001
#>
[CmdletBinding()]
param(
    [switch]$WithMySQL,
    [switch]$Build,
    [string]$ServiceUrl,
    [string]$ApiBaseUrl = 'http://127.0.0.1:8001',
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if (-not $Python) {
    $Python = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
}
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw '找不到 Python，请使用 -Python 指定已安装后端依赖的解释器。'
}
if (-not (Get-Command corepack -ErrorAction SilentlyContinue)) {
    throw '找不到 Corepack，请先配置项目使用的 Node.js 和 pnpm。'
}

function Invoke-Check {
    param([string]$Label, [string]$Executable, [string[]]$Arguments)
    Write-Host "`n$Label" -ForegroundColor Cyan
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label 失败，退出码 $LASTEXITCODE"
    }
}

$savedEnvironment = @{}
$environmentKeys = @(
    'ENVIRONMENT', 'PYTHONIOENCODING', 'ASSETFLOW_MYSQL_TESTS',
    'VITE_API_BASE_URL', 'VITE_APP_WS_ENDPOINT'
)
foreach ($key in $environmentKeys) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}

Push-Location $projectRoot
try {
    $env:ENVIRONMENT = 'dev'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:ASSETFLOW_MYSQL_TESTS = if ($WithMySQL) { '1' } else { '0' }
    if ($WithMySQL) {
        Write-Host 'MySQL 检查复用开发库；普通事务回滚，并发用例短暂提交并清理自身数据。'
    }

    Set-Location (Join-Path $projectRoot 'backend')
    Invoke-Check -Label 'Backend Ruff (AssetFlow and health probes)' -Executable $Python -Arguments @(
        '-m', 'ruff', 'check', '--no-fix', 'app/plugin/module_asset',
        'app/alembic/versions', 'app/alembic/env.py', 'app/core/database.py',
        'app/api/v1/module_common/health/controller.py', 'tests'
    )
    Invoke-Check -Label 'Backend tests' -Executable $Python -Arguments @(
        '-m', 'pytest', 'tests', '-q', '--tb=short'
    )

    Set-Location (Join-Path $projectRoot 'frontend/web')
    $sourceFiles = @(
        'src/api/module_asset/asset.ts',
        'src/views/module_asset/components/AssetPage.vue',
        'src/views/module_asset/components/WatchStatus.vue',
        'src/views/module_asset/overview/index.vue',
        'src/views/module_asset/items/index.vue',
        'src/views/module_asset/applications/index.vue',
        'src/views/module_asset/audit/index.vue'
    )
    Invoke-Check -Label 'Frontend Prettier' -Executable 'corepack' -Arguments (@(
        'pnpm', 'exec', 'prettier', '--check'
    ) + $sourceFiles)
    Invoke-Check -Label 'Frontend ESLint' -Executable 'corepack' -Arguments (@(
        'pnpm', 'exec', 'eslint'
    ) + $sourceFiles)
    Invoke-Check -Label 'Frontend Stylelint' -Executable 'corepack' -Arguments (@(
        'pnpm', 'exec', 'stylelint'
    ) + @($sourceFiles | Where-Object { $_.EndsWith('.vue') }))

    if ($Build) {
        $apiUri = [Uri]$ApiBaseUrl
        if (-not $apiUri.IsAbsoluteUri -or $apiUri.Scheme -notin @('http', 'https')) {
            throw '-ApiBaseUrl 必须为 http 或 https 绝对地址。'
        }
        $env:VITE_API_BASE_URL = $ApiBaseUrl.TrimEnd('/')
        $wsUri = [UriBuilder]::new($apiUri)
        $wsUri.Scheme = if ($apiUri.Scheme -eq 'https') { 'wss' } else { 'ws' }
        $env:VITE_APP_WS_ENDPOINT = $wsUri.Uri.AbsoluteUri.TrimEnd('/')
        Invoke-Check -Label 'Frontend type check and build' -Executable 'corepack' -Arguments @(
            'pnpm', 'run', 'build'
        )
        Write-Host "构建产物：$(Join-Path $projectRoot 'frontend/web/dist')"
    } else {
        Invoke-Check -Label 'Frontend type check' -Executable 'corepack' -Arguments @(
            'pnpm', 'run', 'type-check'
        )
    }

    if ($ServiceUrl) {
        # 直接连接已运行的服务；禁止系统代理把本机检查转发到其他地址。
        Add-Type -AssemblyName System.Net.Http
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $handler.UseProxy = $false
        $client = [System.Net.Http.HttpClient]::new($handler)
        $client.Timeout = [TimeSpan]::FromSeconds(10)
        try {
            foreach ($path in @('/common/health/', '/common/health/ready/', '/asset/item/list')) {
                $url = $ServiceUrl.TrimEnd('/') + '/api/v1' + $path
                $response = $client.GetAsync($url).GetAwaiter().GetResult()
                try {
                    $expected = if ($path -eq '/asset/item/list') { 401 } else { 200 }
                    if ([int]$response.StatusCode -ne $expected) {
                        throw "服务检查 $path 返回 $([int]$response.StatusCode)，预期 $expected"
                    }
                    $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
                    if ($expected -eq 200 -and -not $body.success) {
                        throw "服务检查 $path 返回业务失败"
                    }
                    if ($path -eq '/common/health/ready/' -and (
                        $body.data.checks.database -ne $true -or $body.data.checks.redis -eq $false
                    )) {
                        throw '数据库或 Redis 尚未就绪'
                    }
                    Write-Host "服务检查 $path : $expected"
                } finally {
                    $response.Dispose()
                }
            }
        } finally {
            $client.Dispose()
            $handler.Dispose()
        }
    }
    Write-Host "`n所选检查全部通过。未选择的 MySQL、构建或在线检查未执行。" -ForegroundColor Green
} finally {
    Pop-Location
    foreach ($key in $environmentKeys) {
        [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process')
    }
}
