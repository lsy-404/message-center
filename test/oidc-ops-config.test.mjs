import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const helper = readFileSync(new URL('../bridge/scripts/message-secrets.ps1', import.meta.url), 'utf8');
const workerReadme = readFileSync(new URL('../cloudflare-worker/README.md', import.meta.url), 'utf8');
const bridgeReadme = readFileSync(new URL('../bridge/README.md', import.meta.url), 'utf8');
const wrangler = JSON.parse(readFileSync(new URL('../cloudflare-worker/wrangler.jsonc', import.meta.url), 'utf8'));

assert.match(helper, /ConfigureConnectorTokens/);
assert.match(helper, /Invoke-WranglerSecretPut -Name 'CONNECTOR_TOKENS'/);
assert.match(helper, /StandardInput\.WriteLine\(\$Value\)/);
assert.match(helper, /command output was suppressed to protect secret material/);
assert.match(helper, /Read-Host -Prompt 'Enter the confidential OIDC client secret' -AsSecureString/);
assert.match(helper, /ConfigureOidcSecrets/);
assert.match(helper, /OIDC_CLIENT_SECRET/);
assert.match(helper, /SESSION_SECRET/);
assert.match(helper, /wrangler\.local\.jsonc/);
assert.match(helper, /Existing connector and agent secrets were synchronized/);
assert.match(helper, /OIDC browser authentication: unavailable/);
assert.match(helper, /Remove\('ADMIN_TOKEN'\)/);
assert.doesNotMatch(helper, /Values\.ADMIN_TOKEN|CopyAdminPassword|VerifyOnline|password session|api\/auth\/login/);

assert.match(workerReadme, /\/api\/auth\/callback/);
assert.match(workerReadme, /client_secret_basic/);
assert.match(workerReadme, /allow_all/);
assert.match(workerReadme, /oidc_sessions/);
assert.match(bridgeReadme, /ConfigureOidcSecrets/);
assert.doesNotMatch(`${workerReadme}\n${bridgeReadme}\n${JSON.stringify(wrangler)}`, /id\.voidcarve\.com|id\.wuyilingwei\.com/);

assert.deepEqual(wrangler.vars, {
  OIDC_ISSUER: 'https://identity.example.com',
  OIDC_CLIENT_ID: 'message-center-example',
  OIDC_REDIRECT_URI: 'https://message.example.com/api/auth/callback',
});

console.log('OIDC operations configuration checks passed.');
