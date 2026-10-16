# Adapter send timeout

- [x] Raise the public adapter subprocess timeout to 130 seconds to fit the private verified QQ send deadline plus return margin.
- [x] Keep scan, wake, send acceptance, retry, and command lease semantics unchanged.
- [x] Update the focused runtime test and record the contract change.
- [x] Run the full runtime test module and inspect the diff.
