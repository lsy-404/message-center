# Findings

Initial evidence: cleanup timeout is recorded at the five-second cleanup deadline; cleanupIncomplete=false only means force grace did not expire. unloadFinishedMs records async finish callback completion, not successful unload.
