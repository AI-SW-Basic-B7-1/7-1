import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(testDirectory, "..", "..");

test("EC2 Nginx는 정적 파일을 FastAPI로 전달하고 배포 중 응답을 확인한다", async () => {
  const deployScript = await readFile(
    path.join(repositoryRoot, "scripts/ec2/deploy_ec2.sh"),
    "utf8",
  );
  const staticLocationStart = deployScript.indexOf("location /static/ {");
  const staticLocationEnd = deployScript.indexOf("location / {", staticLocationStart);

  assert.notEqual(staticLocationStart, -1);
  assert.notEqual(staticLocationEnd, -1);
  const staticLocation = deployScript.slice(staticLocationStart, staticLocationEnd);
  assert.match(staticLocation, /proxy_pass http:\/\/127\.0\.0\.1:8000;/);
  assert.doesNotMatch(staticLocation, /\balias\s/);
  assert.match(
    deployScript,
    /for static_path in \/static\/css\/style\.css \/static\/js\/api\.js \/static\/js\/auth\.js \/static\/js\/app\.js \/static\/js\/chat-content\.js \/static\/js\/history\.js \/static\/js\/keyboard\.js \/static\/js\/password-validation\.js \/static\/js\/shell\.js/,
  );
  assert.match(deployScript, /timedatectl set-timezone Asia\/Seoul/);
  assert.match(
    deployScript,
    /configured_timezone=.*timedatectl show --property=Timezone --value/,
  );
});

test("EC2 배포는 현재 DATABASE_URL의 DB를 일일 백업 대상으로 사용한다", async () => {
  const deployScript = await readFile(
    path.join(repositoryRoot, "scripts/ec2/deploy_ec2.sh"),
    "utf8",
  );

  assert.match(deployScript, /database_url="\$\(env_value DATABASE_URL\)"/);
  assert.match(deployScript, /realpath -m -- "\$\{PROJECT_DIR\}\/\$\{database_path\}"/);
  assert.match(
    deployScript,
    /0 4 \* \* \* %s DB_PATH=%s BACKUP_DIR=%s RETENTION_DAYS=%s %s/,
  );
  assert.match(
    deployScript,
    /"\$\{APP_USER\}" "\$\{DB_PATH\}" "\$\{BACKUP_DIR\}" "\$\{RETENTION_DAYS\}"/,
  );
  assert.match(deployScript, /KOR_PET_TOUR_SERVICE_KEY가 비어 있습니다/);
});
