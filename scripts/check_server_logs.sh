#!/usr/bin/env bash
# ============================================================================
# B7-1 서버 표준 4대 핵심 이벤트 로깅 검증 스크립트 (Linux / EC2)
# 파일명: scripts/check_server_logs.sh
# 실행법: bash scripts/check_server_logs.sh [로그파일경로]
# ============================================================================

LOG_FILE=""

echo "============================================================"
echo " [B7-1] 서버 4대 핵심 이벤트 로깅 검증: "
echo "============================================================"

if [ ! -f "" ]; then
    echo "⚠️  로그 파일을 찾을 수 없습니다: "
    echo "   (서버가 실행 중이고 logs/server.log에 로그가 기록되고 있는지 확인하세요.)"
    exit 1
fi

echo -e "\n📌 1. 요청 수신 이벤트 (request_received):"
grep "request_received" "" | tail -n 5 || echo "   (기록 없음)"

echo -e "\n📌 2. AI 호출 시작 이벤트 (ai_call_start):"
grep "ai_call_start" "" | tail -n 5 || echo "   (기록 없음)"

echo -e "\n📌 3. AI 호출 성공 및 레이턴시 (ai_call_success):"
grep "ai_call_success" "" | tail -n 5 || echo "   (기록 없음)"

echo -e "\n📌 4. DB 대화 영속 저장 성공 (db_save_success):"
grep "db_save_success" "" | tail -n 5 || echo "   (기록 없음)"

echo -e "\n============================================================"
echo " 최근 4대 이벤트 통합 로그 (최근 10행):"
echo "============================================================"
grep -E "(request_received|ai_call_start|ai_call_success|db_save_success)" "" | tail -n 10
