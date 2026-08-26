# Stage 1 - Scope, Safety, and Acceptance Criteria

## MVP Scope
### In scope manuals
- `tm-9-2320-280-10`
- `TM-9-2320-280-20-1`
- `TM-9-2320-280-20-2`
- `TM-9-2320-280-20-3`

### In scope user journeys
1. Symptom-to-diagnostic guidance.
2. Step-by-step cited procedure guidance.
3. Follow-up troubleshooting questions within the current diagnostic context.

### Explicitly out of scope for this phase
- Image reasoning.
- Voice interaction.
- Predictive maintenance.
- Uncited free-form repair advice.
- Coverage expansion beyond the MVP manuals.

## Operating Modes
### Operator mode
- Primary source emphasis: `tm-9-2320-280-10`.
- Goal: identify simple corrective action or escalation to maintenance.

### Maintenance mode
- Primary source emphasis: `TM-9-2320-280-20-1/2/3`.
- Goal: identify grounded diagnostic and repair procedures with task-level traceability.

## Safety Requirements
1. Always surface relevant warnings, cautions, and notes before the associated procedure or decision step.
2. Never produce procedural guidance without at least one citation to manual, file, and anchor-level provenance.
3. When the source material is ambiguous, conflicting, or absent, respond with insufficient-evidence behavior instead of improvisation.
4. Preserve maintenance ordering when presenting step sequences.
5. Preserve escalation boundaries when the manual directs the user to supervisor, unit maintenance, or another referenced manual.
6. Keep user-visible answers grounded to the selected operating mode to avoid mixing operator and maintenance instructions without notice.

## Acceptance Criteria
### Retrieval and grounding
- The system can limit retrieval to MVP manuals only.
- Every returned answer includes source manual, source path, and source anchor or equivalent chunk identifier.
- Retrieved evidence must map back to exact source excerpts.

### Diagnostic behavior
- Symptom queries return a ranked diagnostic path or an explicit insufficient-evidence response.
- Follow-up questions preserve current manual context and do not silently jump to unrelated subsystems.
- Troubleshooting sequences retain yes/no or ordered decision semantics where the source expresses them.

### Procedure behavior
- Procedure answers maintain source step order.
- `INITIAL SETUP` requirements and `FOLLOW-ON TASKS` remain attached to the same task response.
- Safety blocks attached to a task are shown with that task.

### Offline and operational constraints
- Design assumptions must support fully local execution in later stages.
- No stage 1 artifact should assume a hosted embedding or hosted LLM dependency.

## Review Gates
### Gate 1 - scope fit
- The query can be classified as operator, maintenance, or unsupported.
- Unsupported requests are rejected or narrowed without hallucinated guidance.

### Gate 2 - safety fit
- Answers fail closed when citation or safety attachment is missing.
- High-risk procedural responses cannot bypass associated warnings.

### Gate 3 - evidence fit
- Evidence can be inspected by a reviewer without external systems.
- A reviewer can trace an answer back to a file and excerpt.

## Challenged Assumptions
- Assumption: one generic query flow is enough.
  - Challenge: operator and maintenance journeys have different evidence and escalation expectations.
- Assumption: citations alone make answers safe.
  - Challenge: warnings and order preservation are separate acceptance requirements.
- Assumption: MVP should cover all manuals because they already exist.
  - Challenge: a smaller boundary improves validation quality and safety discipline.

## Decisions Made
1. Use four manuals only for the MVP boundary.
2. Treat operator and maintenance experiences as separate modes sharing a common evidence model.
3. Make insufficient-evidence behavior a first-class success condition, not a failure case.
4. Require source traceability at the content-unit level before later retrieval work begins.

## Open Questions
1. Should the first release force the user to choose operator or maintenance mode, or infer it from the question and cited sources?
2. What threshold should later stages use to decide between ranked guidance and insufficient evidence?
3. Are cross-manual answers allowed when the primary cited task references another manual, or should the system require explicit user confirmation?
