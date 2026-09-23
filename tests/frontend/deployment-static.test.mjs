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
    /for static_path in \/static\/css\/style\.css \/static\/js\/auth\.js \/static\/js\/app\.js/,
  );
  assert.match(deployScript, /timedatectl set-timezone Asia\/Seoul/);
  assert.match(
    deployScript,
    /configured_timezone=.*timedatectl show --property=Timezone --value/,
  );
});
