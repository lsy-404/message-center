import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../bridge/device/native-frida-helper/main.m', import.meta.url), 'utf8');
const docs = await readFile(new URL('../bridge/device/native-frida-helper/README.md', import.meta.url), 'utf8');
const workflow = await readFile(new URL('../.github/workflows/build-native-frida-helper.yml', import.meta.url), 'utf8');

test('helper accepts bounded script input and only the local Frida server', () => {
  assert.match(source, /MAX_INPUT_BYTES \(1024 \* 1024\)/);
  assert.match(source, /"127\.0\.0\.1:27042"/);
  assert.match(source, /frida_device_attach\(/);
  assert.match(source, /frida_script_load\(/);
  assert.doesNotMatch(source, /frida_device_manager_add_remote_device\([^\n]*argv/);
});

test('helper reports uncertain dispatch after script loading starts', () => {
  assert.match(source, /helper\.load_started \? "unknown" : "not_started"/);
  assert.match(source, /frida_script_unload\(/);
  assert.match(source, /frida_session_detach\(/);
  assert.match(source, /frida_device_manager_close\(/);
  assert.match(docs, /dispatch.*unknown/);
});

test('helper latches the first valid send and reserves space for JSON envelopes', () => {
  assert.match(source, /MAX_RESULT_BYTES \(MAX_INPUT_BYTES - 4096\)/);
  assert.match(source, /helper->cleanup_started \|\| helper->result_received \|\| message == NULL/);
  assert.match(source, /payload_data\.length > MAX_RESULT_BYTES/);
  assert.match(source, /data\.length > MAX_INPUT_BYTES/);
});

test('build is manual with a narrow source trigger, pinned devkit, and artifact output', () => {
  assert.match(workflow, /workflow_dispatch:/);
  assert.match(workflow, /push:\s+paths:/);
  assert.match(workflow, /"bridge\/device\/native-frida-helper\/\*\*"/);
  assert.match(workflow, /"\.github\/workflows\/build-native-frida-helper\.yml"/);
  assert.doesNotMatch(workflow, /schedule:/);
  assert.match(workflow, /C31AA39618A6996BF43A472F2F48E3E4C2CC72EEE101A1ED6820192CBF58BDEC/);
  assert.match(workflow, /actions\/upload-artifact/);
  assert.match(workflow, /miphoneos-version-min=15\.0/);
  assert.match(workflow, /permissions:\s+contents: read/);
  assert.match(workflow, /ldid -Cadhoc -S/);
  assert.match(workflow, /every CodeDirectory must carry CS_ADHOC/);
  assert.doesNotMatch(workflow, /contents: write|secrets\./);
});

test('helper embeds no remote service or application-specific endpoint', () => {
  assert.doesNotMatch(source, /https?:\/\//);
  assert.doesNotMatch(source, /getenv\(|SERVICE_URL|REMOTE_HOST/);
});
