# Example: research brief with inspectable citations

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md)

## Goal and starting point

Answer “What does the Atlas launch require?” from a bundled fictional launch packet.
Return a short brief with source IDs and display the source text next to it. Save the
brief as an artifact that can be searched without resending the whole document.

The happy path, invented citation, and empty retrieval all run offline. A charged
retriever wrapper makes retrieval visible in the tool budget. The existing grounding
step validates citation membership, not whether every claim is entailed by its cited
source. Show that boundary explicitly; live claim-support verification is an extension.

| Action | Starting file / role |
| --- | --- |
| Reuse | Feature 09 `GroundedAnswerStep` and `MemoryRetriever`, and feature 10 `ArtifactStore` |
| Add | `examples/implementation/showcase_research.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run and inspect

After the features this showcase needs are in the packages:

```bash
.venv/bin/python examples/implementation/showcase_research.py
```

The feature guide checker does not run this showcase. Run the command above and compare it with the checklist.

The brief lists both launch sources, prints their locators and contents, and exposes
an artifact digest. The failure cases print that an invented source was rejected and
that no generation occurred when retrieval returned nothing. The in-memory artifact
lasts for this process; use feature 10 `FileArtifacts` for durable storage.

## Extend to live use

Inject a feature 04 model and a production Retriever behind the charged wrapper. Keep
retrieval limits and source IDs stable. Add a verifier that checks claim-to-source
support before describing live answers as factually grounded. For private corpora,
authorize retrieval before fetching documents. Evaluate against questions with known
answers and intentionally irrelevant or conflicting evidence.

## Before moving on

- [ ] Only relevant documents are retrieved.
- [ ] Every displayed citation exists in the supplied evidence.
- [ ] Empty retrieval consumes one retrieval call and zero model calls.
- [ ] Invented citation yields `Stopped`, never a published brief.
- [ ] Artifact content includes both the answer and inspectable sources.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
