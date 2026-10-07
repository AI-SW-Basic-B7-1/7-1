#!/usr/bin/env bash
# 프로젝트 운영 로그에 전용 회전 정책과 시간별 검사 예약을 설치합니다.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
POLICY='/etc/b7-1/logrotate.conf'
SCHEDULE='/etc/cron.d/b7-1-logrotate'
STATE_DIR='/var/lib/b7-1-logrotate'

if [[ "${1:-}" == '--help' ]]; then
    printf '%s\n' '사용법: sudo bash scripts/ec2/configure_log_rotation.sh' \
        '매시간 17분에 검사하며 하루 경과 또는 5MiB 초과 시 회전합니다.' \
        '파일별 백업 7개를 보관합니다. 설치 시 강제 회전하지 않습니다.' \
        'server.log는 copytruncate를 사용하므로 복사·비우기 사이 로그 유실 가능성이 있습니다.'
    exit 0
fi
[[ $# -eq 0 ]] || exit 1
[[ $EUID -eq 0 ]] || { printf '%s\n' 'sudo로 실행해 주세요.' >&2; exit 1; }
for command in logrotate systemctl install mktemp; do
    command -v "${command}" >/dev/null || exit 1
done
[[ "${LOG_DIR}" =~ ^/[a-zA-Z0-9_./-]+$ && -d "${LOG_DIR}" && ! -L "${LOG_DIR}" ]] || exit 1
for path in "$(dirname "${POLICY}")" "${POLICY}" "${SCHEDULE}" "${STATE_DIR}"; do
    [[ ! -L "${path}" ]] || { printf '심볼릭 링크는 지원하지 않습니다: %s\n' "${path}" >&2; exit 1; }
done
for path in "${POLICY}" "${SCHEDULE}"; do
    [[ ! -e "${path}" || -f "${path}" ]] || exit 1
done
for name in nginx_access.log nginx_error.log server.log; do
    [[ ! -L "${LOG_DIR}/${name}" ]] || exit 1
done

WORK_DIR="$(mktemp -d)"
CHANGED=0
cleanup() {
    local result=$?
    trap - EXIT
    set +e
    if [[ $result -ne 0 && $CHANGED -eq 1 ]]; then
        for name in policy schedule; do
            if [[ "${name}" == policy ]]; then target="${POLICY}"; else target="${SCHEDULE}"; fi
            if [[ -f "${WORK_DIR}/${name}.backup" ]]; then
                cp -p -- "${WORK_DIR}/${name}.backup" "${target}"
            else
                rm -f -- "${target}"
            fi
        done
        printf '%s\n' '로그 회전 정책과 예약을 이전 상태로 복원했습니다.' >&2
    fi
    rm -rf -- "${WORK_DIR}"
    exit "${result}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 기본 로그 회전 서비스와 중복되지 않도록 별도 설정·상태 파일을 사용합니다.
cat > "${WORK_DIR}/policy" <<EOF
"${LOG_DIR}/nginx_access.log" "${LOG_DIR}/nginx_error.log" {
    su root root
    daily
    maxsize 5M
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    nodateext
    create 0640 root root
    sharedscripts
    postrotate
        if /usr/bin/systemctl is-active --quiet nginx.service; then
            /usr/bin/systemctl kill --kill-who=main --signal=USR1 nginx.service
        fi
    endscript
}

"${LOG_DIR}/server.log" {
    su root root
    daily
    maxsize 5M
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    nodateext
    copytruncate
}
EOF
printf 'SHELL=/bin/sh\nPATH=/usr/sbin:/usr/bin:/sbin:/bin\n17 * * * * root /usr/sbin/logrotate --state %s/status %s\n' \
    "${STATE_DIR}" "${POLICY}" > "${WORK_DIR}/schedule"
logrotate --debug "${WORK_DIR}/policy"
[[ ! -f "${POLICY}" ]] || cp -p -- "${POLICY}" "${WORK_DIR}/policy.backup"
[[ ! -f "${SCHEDULE}" ]] || cp -p -- "${SCHEDULE}" "${WORK_DIR}/schedule.backup"
install -d -o root -g root -m 755 "$(dirname "${POLICY}")"
install -d -o root -g root -m 700 "${STATE_DIR}"
CHANGED=1
install -o root -g root -m 644 "${WORK_DIR}/policy" "${POLICY}"
install -o root -g root -m 644 "${WORK_DIR}/schedule" "${SCHEDULE}"
logrotate --debug "${POLICY}"
systemctl enable --now cron
systemctl is-active --quiet cron
CHANGED=0
printf '%s\n' '로그 회전 정책 설치 완료: 매시간 검사, 하루 경과 또는 5MiB 초과 시 회전, 백업 7개.' \
    '5MiB는 검사 시점의 기준이며 파일 크기의 엄격한 상한이 아닙니다.' \
    'app.log는 Python 회전을 유지합니다. 실제 운영 회전 검증은 별도로 진행하세요.'
