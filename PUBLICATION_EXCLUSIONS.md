# Publication scope

`PUBLICATION_EXCLUSIONS.json` is the candidate-export policy. `.gitignore` also protects the local review workspace and named private historical records. Gitignore does not untrack files already committed: check the staging area before publication. No Git repository or remote was created here.

| Classification | Material | Handling |
|---|---|---|
| Suitable structurally, subject to license approval | Core implementation, examples, established tests, current guides | Include without scientific edits |
| Candidate scientific evidence, rights review required | evidence/ aggregates, role outputs and source hashes | Include in human-review candidate; no history rewriting |
| Requires modification or manual environment review | Historical config/script absolute paths and remote deployment assumptions | Preserve; list in review findings; no claim of portable full recomputation |
| Should remain private | docs/audit, manuscript extraction, research_audits, local source inventory and old review reports | Exclude from export and tracking; retain locally |
| Should remain private | Credentials, .env, raw datasets, SQLite stores, caches and generated runs | Exclude; no raw data copied |
| Requires author authorization | LICENSE and third-party evidence redistribution | Blocking decision; no automatic authorization |

The public candidate excludes private review history, not inconvenient scientific limitations. Original configurations, results and case records remain intact. Large files in evidence are useful verification inputs, not redundant logs. Duplicate role files may correspond to both a role record and a feedback-chain reference; retain these explicit relationships rather than deduplicating blindly.

Targeted addition: `stage2_validation/transfer_day8.py` is excluded from the public candidate. The historical file remains in the preparation copy unchanged. No package/test/example imports this transfer-only utility; download and remote-upload commands were not executed.
