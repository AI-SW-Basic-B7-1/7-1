#!/usr/bin/env bash
# 지정한 전용 테스트 EC2의 기본 도구·표식·복원 전제조건을 준비합니다.

set -Eeuo pipefail
umask 077

EXPECTED_INSTANCE_ID="${EXPECTED_INSTANCE_ID:-}"
AWS_REGION="${E2E_AWS_REGION:-}"
SECRET_PARAMETER="${E2E_SECRET_PARAMETER:-}"
MARKER='/etc/b7-1/e2e-test-instance'
ENV_TEMP=''

fail() {
    printf '[실패] %s\n' "$*" >&2
    exit 1
}

cleanup() {
    [[ -n "${ENV_TEMP}" ]] && rm -f -- "${ENV_TEMP}"
}
trap cleanup EXIT

[[ "$(id -u)" -eq 0 ]] || fail 'root 권한이 필요합니다.'
[[ "${EXPECTED_INSTANCE_ID}" =~ ^i-[0-9a-f]{17}$ ]] || fail '기대 EC2 ID 형식이 올바르지 않습니다.'
[[ "${AWS_REGION}" == ap-northeast-2 ]] || fail '허용한 AWS 리전이 아닙니다.'
[[ "${SECRET_PARAMETER}" =~ ^/[A-Za-z0-9_./-]+$ ]] || fail 'Parameter Store 이름이 올바르지 않습니다.'
metadata_token="$(curl -fsS --connect-timeout 2 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)"
actual_instance="$(curl -fsS --connect-timeout 2 -H "X-aws-ec2-metadata-token: ${metadata_token}" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || true)"
unset metadata_token
[[ "${actual_instance}" == "${EXPECTED_INSTANCE_ID}" ]] || fail '실제 서버가 지정 테스트 EC2와 다릅니다.'

if [[ -e "${MARKER}" || -L "${MARKER}" ]]; then
    [[ -f "${MARKER}" && ! -L "${MARKER}" ]] || fail '기존 테스트 표식이 일반 파일이 아닙니다.'
    [[ "$(stat -c '%U:%a' "${MARKER}")" == 'root:600' ]] || fail '기존 테스트 표식 권한이 올바르지 않습니다.'
else
    install -d -o root -g root -m 755 /etc/b7-1
    (umask 077; printf '%s\n' 'B7-1 E2E 테스트 EC2' > "${MARKER}")
    chown root:root "${MARKER}"
    chmod 600 "${MARKER}"
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates certbot cron curl git logrotate nginx python3 python3-pip \
    python3-venv sqlite3 unzip
[[ "$(uname -m)" == x86_64 ]] || fail '현재 준비 스크립트는 x86_64 테스트 EC2만 지원합니다.'
if ! command -v aws >/dev/null 2>&1; then
    aws_temp="$(mktemp -d /tmp/b7-1-aws-cli.XXXXXXXX)"
    curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o "${aws_temp}/awscliv2.zip"
    unzip -q "${aws_temp}/awscliv2.zip" -d "${aws_temp}"
    "${aws_temp}/aws/install"
    rm -rf -- "${aws_temp}"
fi
command -v fallocate >/dev/null 2>&1 || fail 'Swap 준비에 필요한 fallocate 명령이 없습니다.'
if ! swapon --show=NAME --noheadings | awk '{print $1}' | grep -Fxq /swapfile; then
    [[ ! -e /swapfile && ! -L /swapfile ]] || fail '비활성 상태의 /swapfile이 이미 있습니다.'
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
fi
grep -Fqx '/swapfile none swap sw 0 0' /etc/fstab || printf '%s\n' '/swapfile none swap sw 0 0' >> /etc/fstab

ENV_TEMP="$(mktemp /run/b7-1-e2e-environment.XXXXXXXX)"
chmod 600 "${ENV_TEMP}"
aws --region "${AWS_REGION}" ssm get-parameter \
    --name "${SECRET_PARAMETER}" \
    --with-decryption \
    --query Parameter.Value \
    --output text > "${ENV_TEMP}"
[[ -s "${ENV_TEMP}" ]] || fail '지정 SecureString이 비어 있습니다.'
for key in SECRET_KEY GEMINI_API_KEY DATABASE_URL SITE_DOMAIN; do
    grep -Eq "^${key}=.+$" "${ENV_TEMP}" || fail "SecureString 필수 항목을 확인하지 못했습니다: ${key}"
done
database_url="$(sed -n 's/^DATABASE_URL=//p' "${ENV_TEMP}" | head -n 1)"
[[ "${database_url}" == sqlite:///* ]] || fail 'SecureString DB가 SQLite 경로가 아닙니다.'
unset database_url

os_version="$(. /etc/os-release && printf '%s' "${VERSION_ID:-unknown}")"
memory_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
swap_kb="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"
printf 'E2E_INSTANCE_PREFLIGHT=passed instance=%s os=%s arch=%s memory_kb=%s swap_kb=%s aws_cli=installed marker=root:600\n' \
    "${actual_instance}" "${os_version}" "$(uname -m)" "${memory_kb}" "${swap_kb}"
