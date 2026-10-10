import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../bridge/device/native-frida-helper/main.m', import.meta.url), 'utf8');
const docs = await readFile(new URL('../bridge/device/native-frida-helper/README.md', import.meta.url), 'utf8');
const workflow = await readFile(new URL('../.github/workflows/build-native-frida-helper.yml', import.meta.url), 'utf8');
const binaryOutput = await readFile(new URL('../bridge/device/native-frida-helper/binary-output.c', import.meta.url), 'utf8');
const binaryOutputHeader = await readFile(new URL('../bridge/device/native-frida-helper/binary-output.h', import.meta.url), 'utf8');

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

test('script eternalization is opt-in and follows only a valid setup result', () => {
  assert.match(source, /gboolean eternalize_requested;/);
  assert.match(source, /strcmp\(argv\[i\], "--eternalize"\)/);
  assert.match(source, /helper->eternalize_requested && helper->result_received &&\s+helper->error_code == NULL/);
  assert.match(source, /frida_script_eternalize\(helper->script/);
  assert.match(source, /frida_script_eternalize_finish\(/);
  assert.match(source, /helper->script_eternalized = TRUE;/);
  assert.ok(source.includes('"{\\"type\\":\\"native-helper-eternalized\\"}"'));
  const eternalizeCallback = source.match(/on_script_eternalized\([\s\S]*?(?=static void\ncomplete_script)/)?.[0];
  assert.ok(eternalizeCallback);
  assert.match(eternalizeCallback,
    /if \(error != NULL\) \{[\s\S]*?start_cleanup\(helper\);\s+return;\s+\}[\s\S]*?helper->script_eternalized = TRUE;[\s\S]*?frida_script_post\(helper->script,[\s\S]*?start_cleanup\(helper\);/);
  assert.ok(eternalizeCallback.indexOf('helper->script_eternalized = TRUE;') <
    eternalizeCallback.indexOf('frida_script_post('));
  assert.ok(eternalizeCallback.indexOf('frida_script_post(') <
    eternalizeCallback.lastIndexOf('start_cleanup(helper);'));
  assert.ok(source.includes('output[@"scriptLifetime"] = @"eternalized";'));
  assert.match(source, /\(!helper\.eternalize_requested \|\| helper\.script_eternalized\)/);
  assert.match(source, /if \(helper->script_eternalized\) \{\s+detach_session\(helper\);/);
  assert.match(docs, /--eternalize/);
  assert.match(docs, /without unloading the script/);
  assert.match(docs, /native-helper-eternalized/);
  assert.match(docs, /event is never posted when eternalization fails/);
});

test('helper latches the first valid send and reserves space for JSON envelopes', () => {
  assert.match(source, /MAX_RESULT_BYTES \(MAX_INPUT_BYTES - 4096\)/);
  assert.match(source, /if \(helper->result_received\)/);
  assert.match(source, /payload_data\.length > MAX_RESULT_BYTES/);
  assert.match(source, /data\.length > MAX_INPUT_BYTES/);
});

test('binary output is opt-in, single-result, bounded, and excludes payload bytes from stdout', () => {
  assert.match(source, /--binary-output-fd/);
  assert.match(source, /--max-binary-bytes/);
  assert.match(source, /g_bytes_get_size\(data\)/);
  assert.match(source, /g_bytes_get_data\(data, &bytes_length\)/);
  assert.match(source, /declared_bytes != binary_length/);
  assert.match(source, /binary_output_write\(/);
  assert.match(source, /binary_output_reset\(/);
  assert.match(source, /if \(helper->result_received\)/);
  assert.match(source, /if \(helper->cleanup_started\)/);
  assert.match(source, /binaryWritten/);
  assert.match(binaryOutputHeader, /BINARY_OUTPUT_MAX_BYTES \(50u \* 1024u \* 1024u\)/);
  assert.match(binaryOutput, /S_ISREG\(metadata\.st_mode\)/);
  assert.match(binaryOutput, /metadata\.st_size != 0/);
  assert.match(binaryOutput, /O_ACCMODE\) == O_RDONLY/);
  assert.match(binaryOutput, /errno == EINTR/);
  assert.match(docs, /caller.*verify the descriptor size/i);
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
  assert.match(workflow, /-framework,CoreFoundation/);
  assert.match(workflow, /permissions:\s+contents: read/);
  assert.match(workflow, /ldid -Cadhoc -S/);
  assert.match(workflow, /every CodeDirectory must carry CS_ADHOC/);
  assert.doesNotMatch(workflow, /contents: write|secrets\./);
});

test('helper embeds no remote service or application-specific endpoint', () => {
  assert.doesNotMatch(source, /https?:\/\//);
  assert.doesNotMatch(source, /getenv\(|SERVICE_URL|REMOTE_HOST/);
});

test('device instructions separate the executable from adapter state', () => {
  assert.match(docs, /\/var\/jb\/usr\/local\/libexec\/message-center/);
  assert.match(docs, /status, queues, and databases under `\/var\/mobile\/Library\//);
});
