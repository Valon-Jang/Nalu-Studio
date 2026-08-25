# FAST Speaker verification protocol

For every FAST Speaker stage or fix, run the focused deterministic checks and record their command and result in that stage's report.

If verification finds a defect, fix only the current stage scope and run the affected checks again. Record each verification pass, the finding, the correction, and the final clean result. Stop a stage only after a clean verification pass finds no remaining in-scope defect. Integration checks that require the local Chatterbox runtime are recorded separately from deterministic checks.
