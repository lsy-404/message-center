# Findings

- Frida 16.3.3's official C header declares `frida_script_eternalize`, `_finish`, and `_sync`; the public native helper already links the pinned 16.3.3 devkit.
- Frida's implementation moves an eternalized script out of normal session ownership and keeps the agent main loop resident. The helper can therefore opt in after a setup result and close its own session without unloading the QJS script.
- This generic helper lifecycle does not itself provide a later command channel or prove native callback cardinality. Those remain responsibilities of the private coordinator and SDK contract investigation.
