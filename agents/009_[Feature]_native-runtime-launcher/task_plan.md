# Native runtime launcher

- [x] Inspect iOS memorystatus API and existing launchd/workflow constraints.
- [x] Implement a C launcher that sets and reads back its own finite limits before direct exec.
- [x] Update the launchd example, concise device-install instructions, and artifact workflow.
- [x] Add focused tests proving invalid inputs and failed kernel calls never exec.
- [x] Run local checks.
- [x] Commit and trigger the scoped CI build.
- [x] Record device-verification boundary and report the artifact run.
