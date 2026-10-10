# Findings

- The helper retains the first valid script `send` as the result and only requests eternalization when `--eternalize` is set. Eternalization failure returns through cleanup before the success flag is set.
- The local pinned Frida 16.3.3 devkit header declares `void frida_script_post (FridaScript * self, const gchar * json, GBytes * data);`. The acknowledgement can be sent after `frida_script_eternalize_finish` succeeds and after `script_eternalized` becomes true, before cleanup detaches the session.
- The ordinary helper path must remain unchanged. No private script/class/selector details belong in the public helper.
