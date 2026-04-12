---
title: ShadowCull
colorFrom: purple
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# ShadowCull: Legacy Migration & Shadow Dependency Decommission Environment

One-line thesis: Safely migrate legacy business logic to Python while hunting down, proving, and decommissioning undocumented shadow dependencies without triggering cascading failures.

## Overview

ShadowCull is a deterministic OpenEnv environment for safe legacy modernization under hidden dependency risk. An agent must migrate a small legacy DSL (LegacyLang) into Python while correctly handling undocumented shadow dependencies that may be:

- dead / orphaned,
- false positives,
- stateful zombies,
- or critically active for parallel systems.

This environment is intentionally not a generic coding benchmark. It is a focused modernization-failure engine designed to test architectural reasoning, safe dependency severance, side-effect preservation, and destructive-action safety.

## ShadowCull as a Modernization Failure Engine

Each of the three canonical tasks is a curated modernization hazard bundle designed to test specific risks. By treating migration not merely as syntax translation but as a systems architecture problem, ShadowCull models multiple modernization failure classes through latent composition.

This environment is a focused emulator of these failure paths, not a fully generic enterprise migration simulator.

## Scope of Simulation

### What ShadowCull Models

- Hidden risks of pulling forward undocumented legacy dependencies during modernization.
- Safe dependency severance without causing outages.
- The necessity of equivalence testing before decommissioning infrastructure.
- Architectural reasoning about state mutations, orphaned reads, and unsafe destructive actions.

### What ShadowCull Intentionally Excludes

- General-purpose programming benchmarks.
- Broad enterprise migration simulation (database migration, CI/CD, distributed rollout, etc.).
- Real network calls.
- Heavy compilers or external build systems.
- Stochastic evaluation or subjective LLM-as-a-judge scoring.

## Five Hazard Axes

Each hazard bundle is constructed along five explicit axes:

1. Logic Pathology
   The structural defect in the legacy code (e.g., dead code paths, hidden mutation).

2. Dependency Topology
   How the code connects to external systems (e.g., isolated, orphaned read-only shadow dependency, stateful zombie).

3. Data Semantics
   How values flow, mutate, or are ignored through the system.

4. Operational Constraint
   The rules the agent must follow to safely migrate (e.g., preserve mutations, avoid premature culls, prune unused reads).

5. Governance Requirement
   The actual safety condition for success (e.g., decommission safely after proof, preserve side-effects without double-mutation).

## Why this is a Real-World Task

In real enterprise modernization, translating old code into a new language is only half the problem. The larger danger lies in undocumented “shadow” APIs—legacy endpoints that may still be present in the code path but are:

- unused and safe to remove,
- silently mutating state,
- or still required by other critical systems.

A correct agent must not:

- blindly port the legacy dependency into Python,
- decommission an endpoint too early,
- or submit a migration without proof of equivalence.

Instead, it must gather evidence, test equivalence, reason about side effects, and perform safe endpoint handling.

## Deterministic Engine Thesis

ShadowCull is built on a lightweight deterministic engine:

1. LegacyLang
   A tiny custom DSL representing the legacy system.

2. Equivalence Sandbox
   A restricted execution environment that tests submitted Python code against legacy behavior.

3. In-Memory API Simulation
   Simulates endpoints and hidden topology:
   - orphaned endpoints,
   - zombie endpoints,
   - active critical endpoints,
   - false-positive strings.

Because there are no heavy compilers or real network calls, episodes run deterministically and quickly, making the environment practical for hackathon evaluation.

## LegacyLang Overview

LegacyLang supports a small grammar:

- VAR = VALUE
- VAR = VAR1 + VAR2
- VAR = VAR1 - VAR2
- FETCH ENDPOINT INTO VAR
- MUTATE_STATE KEY VALUE
- RETURN VAR

## Action Space

The environment uses a compact typed action space:

1. read_legacy_file
   Reveal the contents of a legacy artifact.

2. ping_endpoint
   Probe an endpoint to gather hints.

3. test_equivalence
   Run the sandbox against submitted Python code.

4. decommission_endpoint
   Attempt to safely turn off an endpoint.

5. submit_migration
   Finalize the migration.

## Observation Space

Observations expose partial evidence only. The agent must explore to uncover the full system topology.

Typical observation fields include:

- task_id
- current_artifact_id
- legacy_file_contents
- discovered_endpoints
- endpoint_status_hints
- equivalence_status
- equivalence_diff_report
- allowed_actions
- failure_modes
- remaining_budget
- message

## Hidden State & Failure Grammar

The hidden state contains the true dependency structure, including:

- hidden active endpoints,
- hidden mutating endpoints,
- hidden false-positive strings.

### Failure Conditions

ShadowCull models the following terminal failure modes:

1. SHADOW_PORTED
   Ported an unnecessary legacy dependency into Python.

2. PREMATURE_CULL
   Decommissioned an endpoint before proving equivalence.

3. UNPROVEN_EQUIVALENCE
   Submitted a migration without a passing equivalence test.

4. FALSE_CULL
   Decommissioned a non-existent or critical endpoint.

5. CASCADE_FAILURE
   Decommissioned an endpoint required by another live system.

6. STATEFUL_ZOMBIE_UNHANDLED
   Left a zombie mutation dependency unresolved.

## Where Zombie APIs Fit

Zombie APIs are one specific dependency-topology variant inside ShadowCull. They are central to the hard task (task_3_stateful), but they do not define the entire environment. ShadowCull is broader than zombie handling: it includes pure translation, orphaned reads, and stateful side-effect migration.

## Canonical Tasks

### 1. Easy — Pure Translation (task_1_pure)
- Stateless LegacyLang logic.
- No real dependency to cull.
- Contains only a false-positive string.
- Goal: produce semantically equivalent Python.

### 2. Medium — The Orphaned API (task_2_orphan)
- Legacy code fetches from an orphaned endpoint.
- The fetched value is ignored.
- Goal:
  - write Python without the fetch,
  - prove equivalence,
  - decommission the orphan safely.

### 3. Hard — The Stateful Strangler (task_3_stateful)
- Legacy code mutates state through a zombie API.
- Goal:
  - preserve the mutation natively in Python,
  - prove equivalence,
  - safely cull the zombie endpoint,
  - avoid hidden critical active dependencies.

## Reward Design

Step rewards are separate from final score.

- Step Penalties
  Small negative rewards for exploration.

- Milestone Rewards
  Moderate rewards for successful reads and equivalence progress.

- Severe Penalties
  Large negative rewards for boundary violations.

- Jackpot
  Best outcome for safe migration plus correct dependency handling.

## Deterministic Final Grading

Final task scores are deterministic and normalized to [0.0, 1.0].

### Rubric
- Semantic Equivalence — 0.4
- Correct Endpoint Handling / Safe Decommission — 0.4
- Efficiency / Budget — 0.2

Failure modes can strictly cap the final score
(e.g. CASCADE_FAILURE = 0.0, SHADOW_PORTED capped at 0.5).

## Baseline Inference Strategy

The submitted root inference.py implements an LLM-orchestrated baseline.

### High-level strategy
- For translation-heavy tasks (especially task_1_pure), the baseline first creates a deterministic Python draft from observed LegacyLang.
- It validates that draft through test_equivalence.
- If equivalence fails, it attempts a repair using equivalence diff signals.
- For dependency-sensitive tasks (task_2_orphan, task_3_stateful), the LLM handles staged evidence gathering, endpoint reasoning, safe submission order, and safe decommission logic.

This hybrid design intentionally reduces brittle first-pass generation on simple translation subtasks while preserving the LLM’s role in reasoning, repair, and action choice.

## Repository Structure

```text
.
├── README.md
├── Dockerfile
├── FINAL_SUBMISSION_CHECKLIST.md
├── app.py
├── grader.py
├── inference.py
├── openenv.yaml
├── pyproject.toml
├── requirements.txt
├── shadow_cull_env_environment.py
├── shadow_cull_env/
│   ├── init.py
│   ├── client.py
│   └── models.py
├── tasks/
│   ├── init.py
│   ├── easy_pure_translation.py
│   ├── medium_orphaned_api.py
│   └── hard_stateful_strangler.py
├── server/
│   ├── init.py
│   ├── app.py
│   ├── grader.py
│   ├── shadow_cull_env_environment.py
│   └── tasks/
└── tests/
    └── test_novelty_invariants.py
```

Official OpenEnv Workflow
# Validate environment compliance
openenv validate .

# Build the environment image
openenv build .

# Push to Hugging Face
openenv push --repo-id <your_hf_username>/shadow_cull_env

Local Server Run
Run the environment server locally:
uv run --project . server
# or
python -m server.app

Local Inference Run
The baseline inference.py is OpenAI-compatible and expects these environment variables:

Required for LLM calls
API_BASE_URL
API_KEY

Optional
MODEL_NAME
ENV_URL
LOCAL_IMAGE_NAME

Example: run against a local server
export API_BASE_URL="https://your-openai-compatible-endpoint/v1"
export API_KEY="your_api_key"
export MODEL_NAME="gemini-2.5-flash-lite"
export ENV_URL="http://localhost:8000"

python inference.py

Example: run against a local Docker image
export API_BASE_URL="https://your-openai-compatible-endpoint/v1"
export API_KEY="your_api_key"
export MODEL_NAME="gemini-2.5-flash-lite"
export LOCAL_IMAGE_NAME="shadowcull-local"

python inference.py

Hugging Face Docker Space Deployment
This repo is configured as a Docker Space.

Build locally
docker build -t shadowcull-local -f server/Dockerfile .

Run locally
docker run -p 7860:7860 shadowcull-local

Health check
curl http://localhost:7860/health

Exposed Endpoints
The FastAPI/OpenEnv server provides:

POST /reset
POST /step
GET /state
GET /schema
GET /health
WS /ws

Validation & Test Commands
# OpenEnv validation
openenv validate .

# Unit / novelty invariants
python -m unittest tests/test_novelty_invariants.py

Why ShadowCull is RL-Worthy
ShadowCull provides a sparse, delayed-reward setting where early destructive actions can permanently ruin the trajectory, but the consequences are only fully realized later. It requires:

exploration,
planning,
equivalence-first reasoning,
staged evidence gathering,
safe destructive-action ordering,
and risk aversion.

That makes it a strong testbed for advanced reasoning and RL-style policy evaluation.