# QQ sticker content repair

## Goal
Render QQ sticker attachments with bounded visual dimensions and truthful labels while preserving the current QQ text-only outbound contract. Validate actual inbound attachment metadata and bytes at existing public boundaries without imposing a global media size limit.

## Scope
Public Vue UI, Worker attachment metadata/byte handling only where needed, and root `/test` semantic tests. No private adapter changes, device operation, deployment, or sends.

## Acceptance
- Sticker-like inbound images render within a small sticker presentation box; ordinary images retain the existing larger image layout.
- UI classification does not leak native sticker type labels or treat unsupported content as sendable.
- Existing declared QQ capabilities remain authoritative; no attachment composer/send path is enabled without verified native support.
- Any public size/dimension validation is bounded, content-aware, and tested at lower/upper/invalid boundaries. Byte limits and display dimensions remain separate.
- Quote UI coordination is limited to shared contracts if necessary.
- [x] Trace current attachment metadata, byte validation, UI classification, and capability declarations.
- [x] Define the smallest public contract correction supported by current code and verified native evidence.
- [x] Implement sticker rendering/label handling and narrowly scoped metadata/byte gates if justified.
- [x] Add semantic root `/test` coverage for behavior and negative boundaries.
- [x] Run targeted validation, review the diff for task/audit leakage, and commit the scoped change.
- [x] Report contracts and any native evidence still required.

## Canonical R2 repair follow-up
- [x] Review duplicate-row repair binding and object checksum handling.
- [x] Repair a present-but-mismatched canonical object only after an exact database/request binding.
- [x] Reconcile ambiguous canonical puts using exact HEAD size and SHA-256, without deleting the canonical key.
- [x] Add root `/test` fault coverage and run the Worker schema suite.
- [x] Require JSON numeric attachment byte lengths and reject boolean/string coercions.
- [x] Use a runtime-recognized fixed-length stream for bounded inbound R2 writes and verify overflow/underflow in the strict test fixture.
