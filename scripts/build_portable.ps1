[CmdletBinding()]
param(
    [string]$Version = "1.0.0",
    [string]$DistRoot = "",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

function Assert-ChildPath {
    param([string]$Root, [string]$Candidate)
    $resolvedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $resolvedCandidate = [System.IO.Path]::GetFullPath($Candidate)
    if (-not $resolvedCandidate.StartsWith($resolvedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "目标路径不在发行目录内：$resolvedCandidate"
    }
}

function Copy-Tree {
    param([string]$Source, [string]$Destination, [string[]]$ExcludeDirectories = @())
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "缺少目录：$Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $copyArgs = @($Source, $Destination, "/E", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
    if ($ExcludeDirectories.Count) {
        $copyArgs += "/XD"
        $copyArgs += $ExcludeDirectories
    }
    & robocopy @copyArgs | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "复制失败（robocopy 退出码 $LASTEXITCODE）：$Source"
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot
$workspaceRoot = Split-Path -Parent $projectRoot
if (-not $DistRoot) {
    $DistRoot = Join-Path $workspaceRoot "dist"
}
$DistRoot = [System.IO.Path]::GetFullPath($DistRoot)
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null

$python = Join-Path $projectRoot ".venv/Scripts/python.exe"
$sitePackages = Join-Path $projectRoot ".venv/Lib/site-packages"
$modelFile = Join-Path $projectRoot "model_cache/models--jinaai--jina-embeddings-v2-base-zh/snapshots/c1ff9086a89a1123d7b5eff58055a665db4fb4b9/onnx/model.onnx"
if (-not (Test-Path -LiteralPath $python)) { throw "缺少构建环境：$python" }
if (-not (Test-Path -LiteralPath $modelFile)) { throw "缺少 Jina 模型缓存：$modelFile" }

$pythonVersion = (& $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
if ($pythonVersion -notmatch '^\d+\.\d+\.\d+$') { throw "无法识别 Python 版本：$pythonVersion" }
$cacheRoot = Join-Path $workspaceRoot ".build-cache"
New-Item -ItemType Directory -Force -Path $cacheRoot | Out-Null
$embeddedZip = Join-Path $cacheRoot "python-$pythonVersion-embed-amd64.zip"
if (-not (Test-Path -LiteralPath $embeddedZip)) {
    $url = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embed-amd64.zip"
    Write-Host "下载独立 Python 运行时：$url"
    Invoke-WebRequest -Uri $url -OutFile $embeddedZip
}

$stage = Join-Path $DistRoot ".GZR-portable-v$Version-build"
$final = Join-Path $DistRoot "GZR-portable-v$Version"
$zip = Join-Path $DistRoot "GZR-portable-v$Version.zip"
Assert-ChildPath -Root $DistRoot -Candidate $stage
Assert-ChildPath -Root $DistRoot -Candidate $final
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
if (Test-Path -LiteralPath $final) { throw "发行目录已存在：$final" }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$portableProject = Join-Path $stage "gu-zhen-ren-rag"
New-Item -ItemType Directory -Force -Path $portableProject | Out-Null
Copy-Tree -Source (Join-Path $projectRoot "app") -Destination (Join-Path $portableProject "app") -ExcludeDirectories @("__pycache__")
Copy-Tree -Source (Join-Path $projectRoot "data_jina2") -Destination (Join-Path $portableProject "data_jina2") -ExcludeDirectories @("__pycache__")
Copy-Tree -Source (Join-Path $projectRoot "model_cache") -Destination (Join-Path $portableProject "model_cache") -ExcludeDirectories @("__pycache__")
Copy-Tree -Source (Join-Path $projectRoot "scripts") -Destination (Join-Path $portableProject "scripts") -ExcludeDirectories @("__pycache__")
Copy-Tree -Source (Join-Path $projectRoot "launcher_text") -Destination (Join-Path $portableProject "launcher_text")
foreach ($name in @("README.md", ".env.example", "requirements.txt", "一键启动.bat", "start.bat")) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination (Join-Path $portableProject $name) -Force
}

$runtime = Join-Path $portableProject "runtime/python"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
Expand-Archive -LiteralPath $embeddedZip -DestinationPath $runtime -Force
$pth = Get-ChildItem -LiteralPath $runtime -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "独立 Python 缺少 python*._pth" }
$pthLines = Get-Content -LiteralPath $pth.FullName
$pthLines = $pthLines | ForEach-Object { if ($_ -match '^\s*#\s*import site\s*$') { "import site" } else { $_ } }
Set-Content -LiteralPath $pth.FullName -Value $pthLines -Encoding ascii
Copy-Tree -Source $sitePackages -Destination (Join-Path $runtime "Lib/site-packages") -ExcludeDirectories @("__pycache__", "tests", "test", "docs", "examples")

foreach ($name in @("gu-zhen-ren", "gu-zhenren-lore", "gu_zhen_ren_pdf")) {
    Copy-Tree -Source (Join-Path $workspaceRoot $name) -Destination (Join-Path $stage $name) -ExcludeDirectories @(".git", "__pycache__")
}
Copy-Item -LiteralPath (Join-Path $workspaceRoot "一键启动.bat") -Destination (Join-Path $stage "一键启动.bat") -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "docs/便携版使用说明.txt") -Destination (Join-Path $stage "使用说明.txt") -Force

$portablePython = Join-Path $runtime "python.exe"
& $portablePython -c "import fastapi, fastembed, numpy, onnxruntime, uvicorn; print('portable runtime ok')"
if ($LASTEXITCODE -ne 0) { throw "便携版运行时校验失败" }
if (Test-Path -LiteralPath (Join-Path $portableProject ".env")) { throw "发行目录不应包含 .env" }

Move-Item -LiteralPath $stage -Destination $final
if (-not $SkipZip) {
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -LiteralPath $final -DestinationPath $zip -CompressionLevel Optimal
}

$size = (Get-ChildItem -LiteralPath $final -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host "便携版已构建：$final"
Write-Host ("目录大小：{0:N1} MB" -f ($size / 1MB))
if (-not $SkipZip) {
    Write-Host ("压缩包：{0}（{1:N1} MB）" -f $zip, ((Get-Item -LiteralPath $zip).Length / 1MB))
}
