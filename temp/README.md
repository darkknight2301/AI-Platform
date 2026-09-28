# CommonTP Framework: Execution Ownership Checklist

**Target Audience:** Junior Members, Senior Engineers, and Senior Managers  
**Purpose:** Step-by-step operational checklist for managing end-to-end execution, failure analysis, and closure under the CommonTP Framework.

---

## Phase 1: Planning & Setup
*Ref: See Guideline Document for branch naming conventions and role definitions.*

1. **Create Execution Branch**
   * *Action:* Create an execution branch using the standard format: `execution/<product>_<custom>_<Run Ids>_<Parent Ticket>`.
   * *Example:* `execution/cm9_ibm_ds8k_r3468_r3469_203115`
2. **Macro Availability Check**
   * *Action:* Verify that required macros exist for the specified product, custom SKU, and changelist context.
3. **Test Code Maintenance**
   * *Action:* Update or automate test code based on the approved changelist.
4. **JSON Mapping Generation**
   * *Action:* Generate JSON mapping using all run IDs and case IDs via TestRail integration.
5. **Dry Run Execution**
   * *Action:* Execute the CommonTP framework command using `-co`. 
   * *Note:* Skipped cases indicate incorrect mapping, invalid information, or missing paths.
6. **Mastermap & Case Mapping Updates**
   * *Action:* Run `excel_generator.py` followed by `case_mapping_generator.py` using the product-based Mastermap to update mappings.
7. **FA Code Sync**
   * *Action:* Cherry-pick or copy update code from the FA branch to the execution branch using the designated helper script.
8. **Resource Planning Details Extraction**
   * *Action:* Run the metrics script to output an Excel sheet detailing Setup Selection, Case Types, Execution Duration, Hardware Requirements, and Team Member Count.
9. **Load-Balanced Suite Generation**
   * *Action:* Generate a load-balanced suite via script and distribute test cases across team members based on headcounts and available setups (if Jenkins is unavailable).
10. **Role Assignment Finalization**
    * *Action:* Finalize list of active members working on Execution and Failure Analysis (FA).

---

## Phase 2: Execution (Untested $\rightarrow$ Retest / Passed)

1. **Setup Preparation**
   * *Action:* Flash all required hardware setups cleanly.
2. **Optimal Execution Strategy**
   * *Action:* Members execute assigned cases optimally, strictly utilizing framework tool `--create-suite`.
3. **Feature-Level Halt Threshold**
   * *Action:* If multiple failures occur within a single feature, stop execution immediately and mark them as Failure Analysis (FA) items.
4. **Pre/Post-Condition Management**
   * *Action:* Execute manual setup and teardown steps based on the selected suite or list file.

---

## Phase 3: Failure Analysis (FA) (Retest $\rightarrow$ Passed / Failed)

1. **Resource-Aligned FA Division**
   * *Action:* Divide FAs by feature modules instead of run IDs, mapping them to available resources (setups and team members).
2. **Historical Log Review & Action Tracking**
   * *Action:* Analyze past logs. If a defect was fixed previously, reference that branch history in the action items to verify Merge Requests (MR) during closure.
3. **Unresolved Issue Logging**
   * *Action:* Document any observations that cannot be immediately addressed during current closure into the action item log.

---

## Phase 4: Closure

1. **MR Review**
   * *Action:* Conduct peer and owner reviews of all Merge Requests.
2. **Action Item Sign-off**
   * *Action:* Close out all action items logged during Execution and FA phases to prevent recurring issues.