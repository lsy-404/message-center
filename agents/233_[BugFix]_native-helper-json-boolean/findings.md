# Findings

- Foundation's boxed expression `@(gboolean)` can produce an integer NSNumber because `gboolean` is integer-typed. Python's strict `type(value) is bool` check then rejects the field.
- The production expression now chooses `@YES` or `@NO` explicitly. The contract test requires that exact expression and rejects the boxed integer form.
- A small macOS-host Objective-C Foundation executable serializes integer-equivalent 0 and 1 through the same ternary expression; CI decodes both lines with Python and asserts exact bool types and false/true values. No Frida runtime is involved.
- Existing cleanup timers and control flow are untouched.
