# Day 6 Stage 2 A/B split protocol

This protocol freezes a metadata-only cell split for subsequent internal
held-out validation. It does not perform discovery or validation.

- Universe: exactly the cells admitted by the completed Day 6 perturbation
  scan, including perturbation cells and matched non-targeting controls.
- Unit: individual cell. A and B are mutually exclusive.
- Ratio: 50:50 within each `scan_target × batch × guide_id` stratum; an odd
  remainder is assigned by a seeded stratum hash.
- Seed: `jure-stage2-day6-heldout-v1`.
- Assignment: cells are ranked by a seeded SHA-256 digest and alternated
  between folds. No expression value or candidate result enters assignment.
- Use: A→B and B→A runs must freeze the discovery candidates before reading
  validation-fold effects. Eligibility and validation thresholds are defined
  in a separate analysis protocol before those runs.
- Scope: the assignment supports conditional PSVR with the existing
  341-state catalogue. A strict end-to-end run must rebuild the Stage 1
  catalogue within each discovery fold using the same assignment.
