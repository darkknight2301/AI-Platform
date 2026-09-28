# CommonTP Framework: Branching & Workflow Guidelines

**Target Audience:** Junior Members to Senior Managers  
**Scope:** Governance, branching rules, role responsibilities, and structural workflows.

---

## 1. Roles and Responsibilities

* **Execution Owner:** 
  * Responsible for high-level planning, resource allocation, closure management, and reviews for both Execution and Failure Analysis phases.
  * Escalation point for blockers and queries.
* **Execution & FA Member:** 
  * Responsible for executing assigned test cases, updating mapping files, performing local FA, and closing assigned feature branches. Must sync up with the Execution Owner for any blockers.

---

## 2. Naming Conventions & Templates

* **Branch Name Template:** `execution/<product>_<custom>_<Run Ids (Max. 2)>_<Parent Release Ticket>`
* **Reference Example:** 
  * *Run Names:* `CM9_IBM_DS8K_FIPS_K800_C9M660101C0_203115_Smoke_Sanity (3468)`, `CM9_IBM_DS8K_FIPS_K800_C9M660101C0_203115 (3469)`
  * *Release Tickets:* `203115` (Parent), `203116`, `203117`
  * *Actual Branch:* `execution/cm9_ibm_ds8k_r3468_r3469_203115`

---

## 3. Branching Architecture & Graph

```text
Master/ADL 
  └── execution/cm9_ibm_ds8k_r3468_r3469_203115
        ├── execution/cm9_ibm_ds8k_r3468_r3469_203115_changelist  (Optional)
        ├── execution/cm9_ibm_ds8k_r3468_r3469_203115_feature1    (TO-level Change)
        ├── execution/cm9_ibm_ds8k_r3468_r3469_203115_feature2    (TO-level Change)
        ├── execution/cm9_ibm_ds8k_r3468_r3469_203115_feature3    (TO-level Change)
        └── execution/cm9_ibm_ds8k_r3468_r3469_203115_lib_json    (Lib & JSON level Change)
```

---

## 4. Strict Branching & Commit Rules

1. **Changelist Integration:** Add all changes matching the changelist directly to the main execution branch.
2. **File Threshold for New Branches:** If a change touches more than 3 to 4 files, a separate sub-branch must be created.
3. **Execution Integrity:** Execution of all test runs must take place strictly on the main execution branch.
4. **Feature Branch Isolation:** Team members must create individual feature-specific branches branching off the main execution branch for FA or localized changes.
5. **Feature Scope Limit:** Individual feature branches must contain $\le 3$ modified files.
6. **Separation of Concerns:** Keep separate branches for Library code modifications versus JSON configuration updates where possible.
7. **Priority Reviews:** Changelist branches must be reviewed with high priority and merged into the execution branch prior to starting test runs.
8. **Ownership & Closure:** Respective team members are fully accountable for the lifecycle and closure of their feature branches.
9. **Mandatory Re-execution:** Complete re-execution of affected test runs is required prior to merging any closure branch.
10. **Commit History Preservation:** Do *not* squash commits on the main execution branch during Merge Requests to preserve granular tracking history.
11. **FA Change Isolation:** Any modifications resulting from Failure Analysis require a dedicated, separate branch that must undergo full code review.
12. **Post-Merge FA Verification:** Re-execute all FA-related test cases after merging FA branch updates back into the main execution branch.