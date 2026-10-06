#!/usr/bin/env bash
# 테스트 EC2의 Cron·Certbot·자원 상태를 확인하고 복구 가능한 작업만 실행합니다.

set -Eeuo pipefail
umask 077

RUN_ID="${E2E_RUN_ID:-}"
EXPECTED_INSTANCE_ID="${EXPECTED_INSTANCE_ID:-}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(systemctl show chatbot.service -p WorkingDirectory --value)"
APP_USER="$(systemctl show chatbot.service -p User --value)"
APP_USER="${APP_USER:-ubuntu}"
STATE_ROOT='/var/lib/b7-1/e2e'
CRON_TEST_FILE="/etc/cron.d/b7-1-e2e-${RUN_ID}"
WORK_DIR="${STATE_ROOT}/ops-${RUN_ID}"

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

cleanup() {
    local result=$?
    trap - EXIT
    rm -f -- "${CRON_TEST_FILE}"
    if [[ "${WORK_DIR}" == "${STATE_ROOT}"/ops-* && -d "${WORK_DIR}" && ! -L "${WORK_DIR}" ]]; then
        rm -rf -- "${WORK_DIR}"
    fi
    exit "${result}"
}

[[ "$(id -u)" -eq 0 ]] || fail 'root 권한이 필요합니다.'
[[ "${RUN_ID}" =~ ^[A-Za-z0-9_-]{1,100}$ ]] || fail '실행 ID가 올바르지 않습니다.'
[[ "${EXPECTED_INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '테스트 EC2 ID가 올바르지 않습니다.'
[[ "${APP_USER}" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || fail '앱 서비스 사용자 형식을 확인하지 못했습니다.'
[[ -f /etc/b7-1/e2e-test-instance && ! -L /etc/b7-1/e2e-test-instance ]] || fail '테스트 EC2 표식이 없습니다.'
[[ "$(stat -c '%U:%a' /etc/b7-1/e2e-test-instance)" == 'root:600' ]] || fail '테스트 EC2 표식 권한이 올바르지 않습니다.'
metadata_token="$(curl -fsS --connect-timeout 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)"
actual_instance="$(curl -fsS --connect-timeout 2 -H "X-aws-ec2-metadata-token: ${metadata_token}" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
unset metadata_token
[[ "${actual_instance}" == "${EXPECTED_INSTANCE_ID}" ]] || fail '현재 인스턴스가 지정 테스트 EC2와 다릅니다.'
[[ -d "${STATE_ROOT}" && ! -L "${STATE_ROOT}" && ! -e "${WORK_DIR}" && ! -e "${CRON_TEST_FILE}" ]] || fail 'E2E 임시 작업 경로가 이미 존재하거나 안전하지 않습니다.'
install -o "${APP_USER}" -g "${APP_USER}" -m 700 -d "${WORK_DIR}"
trap cleanup EXIT

systemctl is-active --quiet cron || fail 'Cron 서비스가 실행 중이 아닙니다.'
systemctl is-enabled --quiet cron || fail 'Cron 서비스가 부팅 시 활성화되어 있지 않습니다.'
[[ -f /etc/cron.d/b7-1-chatbot-backup && ! -L /etc/cron.d/b7-1-chatbot-backup ]] || fail '기본 DB 백업 예약을 찾을 수 없습니다.'
grep -Eq "^0 4 \\* \\* \\* ${APP_USER} .*backup_db\\.sh" /etc/cron.d/b7-1-chatbot-backup || fail '기본 백업 예약이 매일 04:00 앱 사용자 실행과 다릅니다.'
database_url="$("${PROJECT_DIR}/venv/bin/python" - "${PROJECT_DIR}/.env" <<'PY'
import sys
from dotenv import dotenv_values

print(dotenv_values(sys.argv[1]).get("DATABASE_URL", ""))
PY
)"
[[ "${database_url}" == sqlite:///* ]] || fail 'SQLite 데이터베이스 경로 형식을 확인하지 못했습니다.'
database_path="${database_url#sqlite:///}"
[[ "${database_path}" == /* ]] || database_path="${PROJECT_DIR}/${database_path}"
database_path="$(realpath -e -- "${database_path}")"
backup_dir="${WORK_DIR}/scheduled-backups"
install -o "${APP_USER}" -g "${APP_USER}" -m 700 -d "${backup_dir}"
cron_log="${WORK_DIR}/cron.log"
chown "${APP_USER}:${APP_USER}" "${WORK_DIR}"
minute="$(date -d '+1 minute' '+%M')"
hour="$(date -d '+1 minute' '+%H')"
printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n%s %s * * * %s DB_PATH=%q BACKUP_DIR=%q RETENTION_DAYS=7 REQUIRE_DB=1 %q >> %q 2>&1\n' \
    "${minute#0}" "${hour#0}" "${APP_USER}" "${database_path}" "${backup_dir}" \
    "${PROJECT_DIR}/scripts/ec2/backup_db.sh" "${cron_log}" > "${WORK_DIR}/cron-file"
install -o root -g root -m 644 "${WORK_DIR}/cron-file" "${CRON_TEST_FILE}"
backup_observed=0
for attempt in $(seq 1 100); do
    shopt -s nullglob
    backups=("${backup_dir}"/chatbot_backup_*.db)
    if (( ${#backups[@]} > 0 )); then
        backup_observed=1
        break
    fi
    sleep 1
done
[[ "${backup_observed}" == 1 ]] || fail '임시 Cron 시간에 백업 명령 실행을 확인하지 못했습니다.'
[[ -f "${backups[0]}" && ! -L "${backups[0]}" ]] || fail 'Cron 백업 파일이 일반 파일이 아닙니다.'
integrity="$(sqlite3 -readonly "${backups[0]}" 'PRAGMA integrity_check;')"
[[ "${integrity}" == ok ]] || fail 'Cron 백업 파일 무결성 검사가 실패했습니다.'
app_home="$(getent passwd "${APP_USER}" | cut -d: -f6)"
[[ -n "${app_home}" ]] || fail '서비스 사용자 홈 경로를 확인하지 못했습니다.'
daily_backup_dir="${app_home}/db_backups"
daily_backup_log="${daily_backup_dir}/backup.log"
daily_cron_prefix="0 4 * * * ${APP_USER} DB_PATH=${database_path} BACKUP_DIR=${daily_backup_dir} "
daily_cron_line="$(grep -F "${daily_cron_prefix}" /etc/cron.d/b7-1-chatbot-backup \
    | grep -F "${PROJECT_DIR}/scripts/ec2/backup_db.sh" || true)"
[[ -n "${daily_cron_line}" ]] || fail '기본 백업 예약이 운영 DB와 기본 백업 경로를 사용하지 않습니다.'
timezone="$(timedatectl show --property=Timezone --value 2>/dev/null || date '+%Z')"
[[ "${timezone}" =~ ^[A-Za-z0-9_+./-]+$ ]] || timezone='unknown'
today="$(date '+%F')"
scheduled_epoch="$(date --date="${today} 04:00:00" '+%s')"
daily_0400_observed=0
cron_event="$(journalctl -t CRON --since "${today} 04:00:00" --until "${today} 04:01:00" --no-pager -o cat 2>/dev/null \
    | grep -F "(${APP_USER}) CMD (" \
    | grep -F "DB_PATH=${database_path}" \
    | grep -F "BACKUP_DIR=${daily_backup_dir}" \
    | grep -F "${PROJECT_DIR}/scripts/ec2/backup_db.sh" || true)"
if [[ -z "${cron_event}" && -f /var/log/syslog && ! -L /var/log/syslog ]]; then
    syslog_day="$(date '+%b %e')"
    cron_event="$(grep -E "^${syslog_day} 04:00:[0-5][0-9]" /var/log/syslog \
        | grep -F "(${APP_USER}) CMD (" \
        | grep -F "DB_PATH=${database_path}" \
        | grep -F "BACKUP_DIR=${daily_backup_dir}" \
        | grep -F "${PROJECT_DIR}/scripts/ec2/backup_db.sh" || true)"
fi
if (( $(date '+%s') >= scheduled_epoch )) \
    && [[ -f "${daily_backup_log}" && ! -L "${daily_backup_log}" ]] \
    && [[ -n "${cron_event}" ]]; then
    daily_entry="$(grep -E "^\\[${today} 04:[0-5][0-9]:[0-5][0-9][+-][0-9]{4}\\] SQLite 백업 완료:" "${daily_backup_log}" | tail -n 1 || true)"
    daily_backup="${daily_entry##*SQLite 백업 완료: }"
    daily_stamp="${daily_entry#\[}"
    daily_stamp="${daily_stamp%%\]*}"
    daily_log_epoch="$(date --date="${daily_stamp}" '+%s' 2>/dev/null || printf '0')"
    if [[ -n "${daily_entry}" \
        && "${daily_log_epoch}" =~ ^[0-9]+$ \
        && "${daily_log_epoch}" -ge "${scheduled_epoch}" \
        && "${daily_log_epoch}" -le "$((scheduled_epoch + 1800))" \
        && "$(dirname -- "${daily_backup}")" == "${daily_backup_dir}" \
        && "$(basename -- "${daily_backup}")" =~ ^chatbot_backup_[0-9]{8}_[0-9]{6}\.db$ \
        && -f "${daily_backup}" && ! -L "${daily_backup}" \
        && "$(stat -c '%U' "${daily_backup}")" == "${APP_USER}" \
        && "$(stat -c '%Y' "${daily_backup}")" -ge "${scheduled_epoch}" \
        && "$(sqlite3 -readonly "${daily_backup}" 'PRAGMA integrity_check;')" == ok ]]; then
        daily_0400_observed=1
    fi
fi
printf 'E2E_O06_CRON_VERIFIED=1 temporary_schedule_observed=1 daily_0400_observed=%s timezone=%s\n' \
    "${daily_0400_observed}" "${timezone}"

systemctl is-enabled --quiet certbot.timer || fail 'Certbot 자동 갱신 타이머가 활성화되어 있지 않습니다.'
systemctl is-active --quiet certbot.timer || fail 'Certbot 자동 갱신 타이머가 실행 중이 아닙니다.'
[[ -x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx ]] || fail 'Nginx 인증서 갱신 후크가 없습니다.'
grep -Fxq 'systemctl reload nginx' /etc/letsencrypt/renewal-hooks/deploy/reload-nginx || fail '인증서 갱신 후크가 Nginx reload를 수행하지 않습니다.'
nginx -t >/dev/null || fail 'Certbot 시험 전 Nginx 문법 검사가 실패했습니다.'
certbot renew --help all 2>&1 | grep -q -- '--run-deploy-hooks' || fail '설치한 Certbot이 배포 후크 시험 옵션을 지원하지 않습니다.'
certbot renew --dry-run --run-deploy-hooks --no-random-sleep-on-renew >/dev/null || fail 'Certbot dry-run 갱신 또는 Nginx reload 후크가 실패했습니다.'
DOMAIN="$("${PROJECT_DIR}/venv/bin/python" - "${PROJECT_DIR}/.env" <<'PY'
import sys
from dotenv import dotenv_values

print(dotenv_values(sys.argv[1]).get("SITE_DOMAIN", ""))
PY
)"
[[ "${DOMAIN}" =~ ^[A-Za-z0-9.-]+$ ]] || fail '사이트 도메인 형식을 확인하지 못했습니다.'
curl --resolve "${DOMAIN}:443:127.0.0.1" --fail --show-error --max-time 10 "https://${DOMAIN}/api/health" >/dev/null || fail '인증서 시험 뒤 HTTPS health 검증이 실패했습니다.'
printf 'E2E_O07_CERTBOT_VERIFIED=1\n'

os_version="$(. /etc/os-release && printf '%s' "${VERSION_ID:-unknown}")"
architecture="$(uname -m)"
cpu_count="$(nproc)"
memory_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
swap_kb="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"
disk_available_kb="$(df -Pk / | awk 'NR == 2 {print $4}')"
service_state="$(systemctl is-active chatbot.service)"
nginx_state="$(systemctl is-active nginx)"
[[ "${service_state}" == active && "${nginx_state}" == active ]] || fail '운영 서비스 또는 Nginx가 active 상태가 아닙니다.'
printf 'E2E_O08_RESOURCES os=%s arch=%s cpu=%s memory_kb=%s swap_kb=%s disk_available_kb=%s chatbot=%s nginx=%s\n' \
    "${os_version}" "${architecture}" "${cpu_count}" "${memory_kb}" "${swap_kb}" "${disk_available_kb}" "${service_state}" "${nginx_state}"
