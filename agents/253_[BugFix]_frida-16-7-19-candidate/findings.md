# Findings

Frida 16.7.19 is an official last-16.x candidate and preserves the existing ObjC bridge and pre-17 Module API surface. The iOS arm64 devkit downloaded from the official GitHub release URL has SHA-256 `90BCA1AE4E8F0DE1BCD70CE9F8E4F1E4635B5D9EF1C5AF97B10880A7BC26C365`.

This change isolates the Frida runtime variable. It does not alter helper cleanup, timeout, script source, or server behavior.