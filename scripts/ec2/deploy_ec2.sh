#!/usr/bin/env bash
# B7-1 EC2 내부 배포 스크립트
# AWS Systems Manager Run Command에서 root 권한으로 실행하는 것을 기준으로 합니다.

set -Eeuo pipefail
umask 027

APP_USER="${APP_USER:-ubuntu}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/app/B7-1/7-1}"
LOG_DIR="${LOG_DIR:-/var/log/b7-1}"
SERVICE_NAME="${SERVICE_NAME:-chatbot.service}"
NGINX_SITE_NAME="${NGINX_SITE_NAME:-chatbot}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
RUN_TESTS="${RUN_TESTS:-1}"
BACKUP_DIR="${BACKUP_DIR:-/home/${APP_USER}/db_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
ENV_FILE="${PROJECT_DIR}/.env"
DB_PATH="${PROJECT_DIR}/data/chatbot.db"

fail() {
    printf '[실패] %s\n' "$*" >&2
    if [[ -n "${LOG_FILE:-}" && -f "${LOG_FILE}" ]]; then
        cat "${LOG_FILE}" >&3 2>/dev/null || true
    fi
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail '이 스크립트는 root 권한으로 실행해야 합니다.'
id "${APP_USER}" >/dev/null 2>&1 || fail "애플리케이션 사용자 계정을 찾을 수 없습니다: ${APP_USER}"
[[ -d "${PROJECT_DIR}" ]] || fail "프로젝트 디렉터리를 찾을 수 없습니다: ${PROJECT_DIR}"
[[ -f "${PROJECT_DIR}/requirements.txt" ]] || fail "requirements.txt를 찾을 수 없습니다: ${PROJECT_DIR}"
[[ -f "${ENV_FILE}" ]] || fail '.env 파일이 없습니다. SSM 실행 시 Parameter Store SecureString을 전달해야 합니다.'
LOGGING_SCRIPT="${PROJECT_DIR}/scripts/ec2/configure_nginx_logs.sh"
[[ -f "${LOGGING_SCRIPT}" ]] || fail '로그 설정 스크립트가 없습니다.'
ROTATION_SCRIPT="${PROJECT_DIR}/scripts/ec2/configure_log_rotation.sh"
[[ -f "${ROTATION_SCRIPT}" ]] || fail '로그 회전 설치 스크립트가 없습니다.'
[[ "${SERVICE_NAME}" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || fail '지원하지 않는 서비스 이름입니다.'
[[ "${NGINX_SITE_NAME}" =~ ^[a-zA-Z0-9_-]+$ ]] || fail '지원하지 않는 사이트 이름입니다.'
[[ "${NGINX_SITE_NAME}" != 'default' ]] || fail '기본 사이트와 다른 이름을 사용해야 합니다.'

APP_HOME="$(getent passwd "${APP_USER}" | cut -d: -f6)"
[[ -n "${APP_HOME}" ]] || fail "사용자의 홈 디렉터리를 확인할 수 없습니다: ${APP_USER}"

mkdir -p "${LOG_DIR}"
chown root:root "${LOG_DIR}"
chmod 700 "${LOG_DIR}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/deploy_$(date +%Y%m%d_%H%M%S).log}"
touch "${LOG_FILE}"
chown root:root "${LOG_FILE}"
chmod 600 "${LOG_FILE}"
exec 3>&1
exec >>"${LOG_FILE}" 2>&1

on_error() {
    local exit_code=$?
    printf '[실패] 줄 번호 %s에서 배포가 중단되었습니다. 종료 코드: %s\n' "${BASH_LINENO[0]:-알 수 없음}" "${exit_code}" >&2
    printf '[실패] 배포 로그: %s\n' "${LOG_FILE}" >&2
    cat "${LOG_FILE}" >&3 2>/dev/null || true
    exit "${exit_code}"
}

trap on_error ERR

log_step() {
    printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

run_cmd() {
    local description="$1"
    shift
    log_step "${description}"
    printf '명령:'
    printf ' %q' "$@"
    printf '\n'
    "$@"
}

run_as_app_in_project() {
    runuser -u "${APP_USER}" -- env HOME="${APP_HOME}" bash -c 'cd "$1"; shift; exec "$@"' bash "${PROJECT_DIR}" "$@"
}

env_value() {
    local key="$1"
    local raw

    raw="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "${ENV_FILE}" | head -n 1 || true)"
    raw="${raw#*=}"
    raw="${raw#"${raw%%[![:space:]]*}"}"
    raw="${raw%"${raw##*[![:space:]]}"}"
    raw="${raw#\"}"
    raw="${raw%\"}"
    printf '%s' "${raw}"
}

log_step '운영 환경변수 필수 항목 확인'
secret_key="$(env_value SECRET_KEY)"
algorithm="$(env_value ALGORITHM)"
gemini_api_key="$(env_value GEMINI_API_KEY)"
database_url="$(env_value DATABASE_URL)"
SITE_DOMAIN="$(env_value SITE_DOMAIN)"
[[ -n "${algorithm}" ]] || algorithm='HS256'
[[ -n "${secret_key}" ]] || fail 'SECRET_KEY가 비어 있습니다.'
secret_key_bytes="$(printf '%s' "${secret_key}" | wc -c)"
[[ "${secret_key_bytes}" -ge 32 ]] || fail 'SECRET_KEY는 UTF-8 기준 32바이트 이상이어야 합니다.'
[[ "${algorithm}" == 'HS256' ]] || fail 'ALGORITHM은 HS256이어야 합니다.'
[[ -n "${gemini_api_key}" ]] || fail 'GEMINI_API_KEY가 비어 있습니다.'
[[ -n "${database_url}" ]] || fail 'DATABASE_URL이 비어 있습니다.'
[[ -n "${SITE_DOMAIN}" && "${SITE_DOMAIN}" =~ ^[A-Za-z0-9.-]+$ && "${SITE_DOMAIN}" != .* && "${SITE_DOMAIN}" != *. ]] || fail 'SITE_DOMAIN에 HTTPS용 도메인을 설정해야 합니다.'
[[ "${secret_key,,}" != *'your_super_secret_jwt_key_here'* ]] || fail 'SECRET_KEY에 예시값이 남아 있습니다.'
[[ "${gemini_api_key}" != *'여기에_본인의_Gemini_API_Key'* ]] || fail 'GEMINI_API_KEY에 예시값이 남아 있습니다.'
unset secret_key secret_key_bytes algorithm gemini_api_key database_url

run_cmd 'EC2 시간대 설정' timedatectl set-timezone Asia/Seoul
configured_timezone="$(timedatectl show --property=Timezone --value)"
[[ "${configured_timezone}" == 'Asia/Seoul' ]] || fail "EC2 시간대 확인에 실패했습니다: ${configured_timezone}"

export DEBIAN_FRONTEND=noninteractive
run_cmd '패키지 목록 갱신' apt-get update
run_cmd '기본 패키지 업그레이드' apt-get upgrade -y
run_cmd '배포 필수 패키지 설치' apt-get install -y acl ca-certificates certbot cron curl git logrotate nginx openssl python3 python3-pip python3-venv sqlite3

log_step '2GB Swap 구성'
if swapon --show=NAME --noheadings | awk '{print $1}' | grep -Fxq "${SWAP_FILE}"; then
    printf '이미 활성화된 Swap 파일을 확인했습니다: %s\n' "${SWAP_FILE}"
elif [[ -e "${SWAP_FILE}" ]]; then
    fail "이미 존재하지만 Swap으로 활성화되지 않은 파일이 있습니다: ${SWAP_FILE}"
else
    run_cmd 'Swap 파일 생성' fallocate -l "${SWAP_SIZE}" "${SWAP_FILE}"
    run_cmd 'Swap 파일 권한 제한' chmod 600 "${SWAP_FILE}"
    run_cmd 'Swap 영역 초기화' mkswap "${SWAP_FILE}"
    run_cmd 'Swap 활성화' swapon "${SWAP_FILE}"
fi

if ! grep -Fqx "${SWAP_FILE} none swap sw 0 0" /etc/fstab; then
    log_step '재부팅 후 Swap 자동 활성화 등록'
    printf '%s none swap sw 0 0\n' "${SWAP_FILE}" >> /etc/fstab
fi
run_cmd '메모리 및 Swap 상태 기록' free -h

run_cmd '프로젝트 소유권 정리' chown -R "${APP_USER}:${APP_USER}" "${PROJECT_DIR}"
run_cmd 'SQLite 데이터 디렉터리 권한 설정' install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "${PROJECT_DIR}/data"
run_cmd '애플리케이션 로그 디렉터리 생성' install -d -o "${APP_USER}" -g "${APP_USER}" -m 750 "${PROJECT_DIR}/logs"
run_cmd 'Nginx 로그 경로 탐색 ACL 설정' setfacl -m u:www-data:--x "${APP_HOME}" "${PROJECT_DIR}/logs"
run_cmd '운영 환경변수 파일 권한 설정' chmod 600 "${ENV_FILE}"

if [[ -f "${DB_PATH}" ]]; then
    run_cmd '기존 SQLite 파일 권한 설정' chmod 600 "${DB_PATH}"
else
    printf '아직 생성되지 않은 SQLite 파일입니다. 애플리케이션 시작 시 생성됩니다: %s\n' "${DB_PATH}"
fi

run_cmd 'Python 가상환경 생성' run_as_app_in_project python3 -m venv venv
run_cmd 'pip 업데이트' run_as_app_in_project "${PROJECT_DIR}/venv/bin/python" -m pip install --upgrade pip
run_cmd 'Python 의존성 설치' run_as_app_in_project "${PROJECT_DIR}/venv/bin/python" -m pip install -r requirements.txt

if [[ "${RUN_TESTS}" == '1' ]]; then
    run_cmd '배포 전 pytest 실행' run_as_app_in_project "${PROJECT_DIR}/venv/bin/python" -m pytest -q
else
    log_step '배포 전 pytest 생략'
fi

NGINX_AVAILABLE="/etc/nginx/sites-available/${NGINX_SITE_NAME}"
NGINX_ENABLED="/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}"
LOGGING_DROPIN="/etc/systemd/system/${SERVICE_NAME}.d/90-b7-1-logging.conf"

# 검증 완료 전까지 설정 원본을 보존합니다. 앱 코드와 DB는 복원 대상이 아닙니다.
CONFIG_BACKUP="$(mktemp -d)"
CONFIG_PATHS=("${NGINX_AVAILABLE}" "${NGINX_ENABLED}" /etc/nginx/sites-enabled/default "${SYSTEMD_UNIT}" "${LOGGING_DROPIN}" /etc/b7-1/logrotate.conf /etc/cron.d/b7-1-logrotate /etc/letsencrypt/renewal-hooks/deploy/b7-1-nginx-reload)
CONFIG_COMMITTED=0
SERVICES_CHANGED=0
SERVICE_ENABLEMENT_CHANGED=0
NGINX_WAS_ACTIVE=0
APP_WAS_ACTIVE=0
CERTBOT_TIMER_WAS_ACTIVE=0
NGINX_WAS_ENABLED=0
APP_WAS_ENABLED=0
CERTBOT_TIMER_WAS_ENABLED=0
systemctl is-active --quiet nginx && NGINX_WAS_ACTIVE=1
systemctl is-active --quiet "${SERVICE_NAME}" && APP_WAS_ACTIVE=1
systemctl is-active --quiet certbot.timer && CERTBOT_TIMER_WAS_ACTIVE=1
systemctl is-enabled --quiet nginx && NGINX_WAS_ENABLED=1
systemctl is-enabled --quiet "${SERVICE_NAME}" && APP_WAS_ENABLED=1
systemctl is-enabled --quiet certbot.timer && CERTBOT_TIMER_WAS_ENABLED=1
for index in "${!CONFIG_PATHS[@]}"; do
    path="${CONFIG_PATHS[$index]}"
    if [[ -e "${path}" || -L "${path}" ]]; then
        cp -a -- "${path}" "${CONFIG_BACKUP}/${index}"
    fi
done
restore_deploy_config() {
    local result=$?
    trap - EXIT
    set +e
    if [[ "${CONFIG_COMMITTED}" -eq 0 ]]; then
        for index in "${!CONFIG_PATHS[@]}"; do
            path="${CONFIG_PATHS[$index]}"
            rm -f -- "${path}"
            if [[ -e "${CONFIG_BACKUP}/${index}" || -L "${CONFIG_BACKUP}/${index}" ]]; then
                cp -a -- "${CONFIG_BACKUP}/${index}" "${path}"
            fi
        done
        systemctl daemon-reload
        if [[ "${SERVICE_ENABLEMENT_CHANGED}" -eq 1 ]]; then
            if [[ "${NGINX_WAS_ENABLED}" -eq 1 ]]; then systemctl enable nginx; else systemctl disable nginx; fi
            if [[ "${APP_WAS_ENABLED}" -eq 1 ]]; then systemctl enable "${SERVICE_NAME}"; else systemctl disable "${SERVICE_NAME}"; fi
            if [[ "${CERTBOT_TIMER_WAS_ENABLED}" -eq 1 ]]; then systemctl enable certbot.timer; else systemctl disable certbot.timer; fi
            if [[ "${CERTBOT_TIMER_WAS_ACTIVE}" -eq 1 ]]; then systemctl start certbot.timer; else systemctl stop certbot.timer; fi
        fi
        if [[ "${SERVICES_CHANGED}" -eq 1 ]]; then
            if [[ "${APP_WAS_ACTIVE}" -eq 1 ]]; then
                systemctl restart "${SERVICE_NAME}" || printf '%s\n' '앱 서비스 복구 실패' >&2
            else
                systemctl stop "${SERVICE_NAME}"
            fi
            if [[ "${NGINX_WAS_ACTIVE}" -eq 1 ]]; then
                nginx -t && systemctl restart nginx || printf '%s\n' 'Nginx 복구 실패' >&2
            else
                systemctl stop nginx
            fi
        fi
        printf '%s\n' '배포 검증 실패: 이전 Nginx·systemd 설정으로 복원했습니다.' >&2
    fi
    rm -rf -- "${CONFIG_BACKUP}"
    exit "${result}"
}
trap restore_deploy_config EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

install_https_site() {
    local site_temp_file
    site_temp_file="$(mktemp)"
    cat > "${site_temp_file}" <<EOF
server {
    listen 80;
    server_name ${SITE_DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://${SITE_DOMAIN}\$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name ${SITE_DOMAIN};
    ssl_certificate /etc/letsencrypt/live/${SITE_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${SITE_DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 2M;

    location ~* \\.(db|sqlite|sqlite3|env|git|log)$ {
        deny all;
        return 404;
    }

    location ^~ /data/ {
        deny all;
        return 404;
    }

    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        expires 1d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 30s;
        proxy_read_timeout 80s;
        proxy_send_timeout 30s;
    }
}
EOF
    install -o root -g root -m 644 "${site_temp_file}" "${NGINX_AVAILABLE}"
    rm -f -- "${site_temp_file}"
}

if [[ -s "/etc/letsencrypt/live/${SITE_DOMAIN}/fullchain.pem" && -s "/etc/letsencrypt/live/${SITE_DOMAIN}/privkey.pem" ]]; then
    install_https_site
else
nginx_temp_file="$(mktemp)"
cat > "${nginx_temp_file}" <<EOF
server {
    listen 80;
    server_name ${SITE_DOMAIN};

    client_max_body_size 2M;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # SQLite 데이터베이스와 환경설정 파일의 외부 다운로드를 차단합니다.
    location ~* \\.(db|sqlite|sqlite3|env|git|log)$ {
        deny all;
        return 404;
    }

    # data 디렉터리 직접 접근을 차단합니다.
    location ^~ /data/ {
        deny all;
        return 404;
    }

    location /static/ {
        return 503;
    }

    location / {
        return 503;
    }
}
EOF
run_cmd 'Nginx 사이트 설정 설치' install -o root -g root -m 644 "${nginx_temp_file}" "${NGINX_AVAILABLE}"
rm -f "${nginx_temp_file}"
fi
run_cmd '기본 Nginx 사이트 비활성화' rm -f /etc/nginx/sites-enabled/default
run_cmd '챗봇 Nginx 사이트 활성화' ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
systemd_temp_file="$(mktemp)"
cat > "${systemd_temp_file}" <<EOF
[Unit]
Description=B7-1 AI 챗봇 FastAPI 서비스
After=network.target

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${PROJECT_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EnvironmentFile=${ENV_FILE}
ExecStart=${PROJECT_DIR}/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
run_cmd 'Systemd 서비스 파일 설치' install -o root -g root -m 644 "${systemd_temp_file}" "${SYSTEMD_UNIT}"
rm -f "${systemd_temp_file}"
run_cmd 'Nginx·서비스 로그 설정 준비' env SITE_CONFIG="${NGINX_AVAILABLE}" SERVICE_NAME="${SERVICE_NAME}" \
    bash "${LOGGING_SCRIPT}" --prepare
SERVICE_ENABLEMENT_CHANGED=1
run_cmd '운영 로그 회전 정책 설치' bash "${ROTATION_SCRIPT}"
run_cmd '최종 Nginx 문법 검사' nginx -t
run_cmd 'Systemd 설정 다시 읽기' systemctl daemon-reload
run_cmd 'Nginx 부팅 자동 시작 설정' systemctl enable nginx
run_cmd '챗봇 서비스 부팅 자동 시작 설정' systemctl enable "${SERVICE_NAME}"
SERVICES_CHANGED=1
run_cmd '챗봇 서비스 재시작' systemctl restart "${SERVICE_NAME}"
run_cmd 'Nginx 재시작' systemctl restart nginx
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    journalctl -u "${SERVICE_NAME}" --no-pager -n 50
    fail "챗봇 서비스가 실행 중이 아닙니다: ${SERVICE_NAME}"
fi

run_cmd 'DB 백업 디렉터리 생성' install -d -o "${APP_USER}" -g "${APP_USER}" -m 700 "${BACKUP_DIR}"
BACKUP_SCRIPT="${PROJECT_DIR}/scripts/ec2/backup_db.sh"
[[ -f "${BACKUP_SCRIPT}" ]] || fail "DB 백업 스크립트를 찾을 수 없습니다: ${BACKUP_SCRIPT}"
run_cmd 'DB 백업 스크립트 실행 권한 설정' chmod 750 "${BACKUP_SCRIPT}"
touch "${BACKUP_DIR}/backup.log"
chown "${APP_USER}:${APP_USER}" "${BACKUP_DIR}/backup.log"
chmod 600 "${BACKUP_DIR}/backup.log"

CRON_FILE='/etc/cron.d/b7-1-chatbot-backup'
cron_temp_file="$(mktemp)"
printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n0 4 * * * %s BACKUP_DIR=%s RETENTION_DAYS=%s %s >> %s 2>&1\n' \
    "${APP_USER}" "${BACKUP_DIR}" "${RETENTION_DAYS}" "${BACKUP_SCRIPT}" "${BACKUP_DIR}/backup.log" > "${cron_temp_file}"
run_cmd 'SQLite 일일 백업 예약 설치' install -o root -g root -m 644 "${cron_temp_file}" "${CRON_FILE}"
rm -f "${cron_temp_file}"
run_cmd 'Cron 부팅 자동 시작 설정' systemctl enable cron
run_cmd 'Cron 재시작' systemctl restart cron

run_cmd 'ACME 챌린지 웹루트 생성' install -d -o root -g www-data -m 2755 /var/www/certbot

run_cmd 'Let’s Encrypt 인증서 발급·갱신' certbot certonly --webroot \
    --webroot-path /var/www/certbot --cert-name "${SITE_DOMAIN}" \
    --domain "${SITE_DOMAIN}" --non-interactive --agree-tos \
    --register-unsafely-without-email --keep-until-expiring
[[ -s "/etc/letsencrypt/live/${SITE_DOMAIN}/fullchain.pem" ]] || fail 'HTTPS 인증서 파일이 없습니다.'
[[ -s "/etc/letsencrypt/live/${SITE_DOMAIN}/privkey.pem" ]] || fail 'HTTPS 개인 키 파일이 없습니다.'
install_https_site
run_cmd 'HTTPS Nginx 로그 설정 준비' env SITE_CONFIG="${NGINX_AVAILABLE}" SERVICE_NAME="${SERVICE_NAME}" \
    bash "${LOGGING_SCRIPT}" --prepare
run_cmd 'HTTPS Nginx 문법 검사' nginx -t
run_cmd 'HTTPS Nginx 설정 적용' systemctl reload nginx
run_cmd 'HTTPS 로그 기록·요청 추적·외부 경로 차단 검증' \
    env SITE_CONFIG="${NGINX_AVAILABLE}" SERVICE_NAME="${SERVICE_NAME}" \
        VERIFY_BASE_URL="https://${SITE_DOMAIN}" bash "${LOGGING_SCRIPT}" --verify
run_cmd '인증서 자동 갱신 타이머 활성화' systemctl enable --now certbot.timer
run_cmd '갱신 후크 디렉터리 생성' install -d -o root -g root -m 755 /etc/letsencrypt/renewal-hooks/deploy
renewal_hook="${CONFIG_BACKUP}/b7-1-nginx-reload"
printf '%s\n' '#!/usr/bin/env bash' 'systemctl reload nginx' > "${renewal_hook}"
run_cmd '인증서 갱신 후크 설치' install -o root -g root -m 750 "${renewal_hook}" /etc/letsencrypt/renewal-hooks/deploy/b7-1-nginx-reload
log_step '서비스 헬스체크 대기'
health_ok=0
for attempt in $(seq 1 30); do
    if curl --resolve "${SITE_DOMAIN}:443:127.0.0.1" -fsS --max-time 3 "https://${SITE_DOMAIN}/api/health"; then
        printf '\n'
        health_ok=1
        break
    fi
    sleep 1
done
[[ "${health_ok}" -eq 1 ]] || {
    journalctl -u "${SERVICE_NAME}" --no-pager -n 50
    fail "HTTPS 헬스체크에 실패했습니다: https://${SITE_DOMAIN}/api/health"
}

for static_path in /static/css/style.css /static/js/auth.js /static/js/app.js; do
    if ! curl --resolve "${SITE_DOMAIN}:443:127.0.0.1" -fsS --max-time 5 "https://${SITE_DOMAIN}${static_path}" -o /dev/null; then
        fail "Nginx 정적 파일 점검에 실패했습니다: ${static_path}"
    fi
done

db_block_status="$(curl --resolve "${SITE_DOMAIN}:443:127.0.0.1" -sS --max-time 5 -o /dev/null -w '%{http_code}' "https://${SITE_DOMAIN}/data/chatbot.db" || true)"
[[ "${db_block_status}" == '404' ]] || fail "Nginx의 DB 파일 차단 검증에 실패했습니다. HTTPS 상태: ${db_block_status}"

redirect_status="$(curl --resolve "${SITE_DOMAIN}:80:127.0.0.1" -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://${SITE_DOMAIN}/api/health" || true)"
[[ "${redirect_status}" == '301' || "${redirect_status}" == '308' ]] || fail "HTTP에서 HTTPS로의 리디렉션 검증에 실패했습니다. HTTP 상태: ${redirect_status}"

[[ -f "${DB_PATH}" ]] || fail "헬스체크 이후에도 SQLite 파일이 생성되지 않았습니다: ${DB_PATH}"
run_cmd 'SQLite 무결성 확인' sqlite3 "${DB_PATH}" 'PRAGMA integrity_check;'
run_cmd '챗봇 서비스 상태 기록' systemctl --no-pager --full status "${SERVICE_NAME}"
CONFIG_COMMITTED=1

log_step 'EC2 배포 완료'
printf '배포 로그: %s\n' "${LOG_FILE}"
printf '애플리케이션 경로: %s\n' "${PROJECT_DIR}"
printf 'Systemd 서비스: %s\n' "${SERVICE_NAME}"
printf 'HTTPS 주소: https://%s\n' "${SITE_DOMAIN}"
printf 'Nginx 보안 검증: HTTP→HTTPS 리디렉션 및 DB 직접 접근 404 확인\n'
printf 'SQLite 백업 예약: 매일 04:00, 보관 기간 %s일\n' "${RETENTION_DAYS}"
cat "${LOG_FILE}" >&3
