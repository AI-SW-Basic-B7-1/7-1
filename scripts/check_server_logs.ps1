<#
.SYNOPSIS
    B7-1 서버 표준 4대 핵심 이벤트 로깅 검증 스크립트 (Windows PowerShell)
.DESCRIPTION
    파일명: scripts/check_server_logs.ps1
    실행법: .\scripts\check_server_logs.ps1 [-LogFile "logs\server.log"]
#>

param(
    [string] = "logs\server.log"
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " [B7-1] 서버 4대 핵심 이벤트 로깅 검증: " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path )) {
    Write-Warning "로그 파일을 찾을 수 없습니다: "
    Write-Host "   (서버가 실행 중이고 logs\server.log에 로그가 기록되고 있는지 확인하세요.)" -ForegroundColor Yellow
    exit 1
}

 = @(
    @{ Name = "1. 요청 수신 이벤트 (request_received)"; Pattern = "request_received" },
    @{ Name = "2. AI 호출 시작 이벤트 (ai_call_start)"; Pattern = "ai_call_start" },
    @{ Name = "3. AI 호출 성공 및 레이턴시 (ai_call_success)"; Pattern = "ai_call_success" },
    @{ Name = "4. DB 대화 영속 저장 성공 (db_save_success)"; Pattern = "db_save_success" }
)

foreach ( in ) {
    Write-Host "
📌 :" -ForegroundColor Green
     = Get-Content  | Select-String -Pattern .Pattern | Select-Object -Last 5
    if () {
         | ForEach-Object { Write-Host "   " }
    } else {
        Write-Host "   (기록 없음)" -ForegroundColor Gray
    }
}

Write-Host "
============================================================" -ForegroundColor Cyan
Write-Host " 최근 4대 이벤트 통합 로그 (최근 10행):" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Get-Content  | Select-String -Pattern "(request_received|ai_call_start|ai_call_success|db_save_success)" | Select-Object -Last 10 | ForEach-Object {
    Write-Host "   "
}
