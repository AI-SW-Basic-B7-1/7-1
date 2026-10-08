<#
.SYNOPSIS
    B7-1 애플리케이션 핵심 이벤트 로그를 확인합니다.
.DESCRIPTION
    기본 로그 경로는 logs/app.log입니다.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$LogFile = "logs/app.log"
)

if (-not (Test-Path -LiteralPath $LogFile -PathType Leaf)) {
    Write-Error "로그 파일을 찾을 수 없습니다: $LogFile"
    exit 1
}

$events = @(
    @{ Name = "요청 수신"; Pattern = "request_received" },
    @{ Name = "AI 호출 시작"; Pattern = "ai_call_start" },
    @{ Name = "AI 호출 성공"; Pattern = "ai_call_success" },
    @{ Name = "AI 호출 실패"; Pattern = "ai_call_failed" },
    @{ Name = "DB 저장 성공"; Pattern = "db_save_success" },
    @{ Name = "DB 저장 실패"; Pattern = "db_save_failed" }
)

foreach ($event in $events) {
    Write-Host ""
    Write-Host "[$($event.Name)]"
    $matchingLines = Get-Content -LiteralPath $LogFile |
        Select-String -SimpleMatch -Pattern $event.Pattern |
        Select-Object -Last 5
    if ($matchingLines) {
        $matchingLines | ForEach-Object { Write-Host $_.Line }
    } else {
        Write-Host "기록 없음"
    }
}
