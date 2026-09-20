-- ============================================================================
-- B7-1 SQLite 대화 이력(chat_logs) 데이터 영속성 및 응답속도 검증 쿼리
-- 파일명: scripts/check_db_chats.sql
-- 실행법: sqlite3 data/chatbot.db < scripts/check_db_chats.sql
-- ============================================================================

.headers on
.mode column

-- 1. 전체 사용자 수 및 총 대화 기록 건수 확인
SELECT 
    (SELECT COUNT(*) FROM users) AS total_users,
    (SELECT COUNT(*) FROM chat_logs) AS total_chats;

-- 2. 최근 10건의 대화 기록 조회 (질문, 응답 앞부분, 응답속도, 생성일시)
SELECT 
    cl.chat_log_id,
    c.conversation_id,
    c.user_id,
    c.title,
    substr(cl.question, 1, 30) AS question_preview,
    substr(cl.response, 1, 30) AS response_preview,
    cl.latency_ms,
    cl.created_at
FROM chat_logs AS cl
JOIN conversations AS c ON c.conversation_id = cl.conversation_id
ORDER BY cl.chat_log_id DESC
LIMIT 10;

-- 3. 사용자별 평균 응답 속도 및 최근 대화 일시 집계
SELECT 
    u.user_id,
    u.username,
    COUNT(cl.chat_log_id) AS chat_count,
    ROUND(AVG(cl.latency_ms), 1) AS avg_latency_ms,
    MAX(cl.created_at) AS last_chat_at
FROM users AS u
LEFT JOIN conversations AS c ON c.user_id = u.user_id
LEFT JOIN chat_logs AS cl ON cl.conversation_id = c.conversation_id
GROUP BY u.user_id, u.username
ORDER BY chat_count DESC;
