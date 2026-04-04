# ShadowCull: Legacy Migration & Shadow Dependency Decommission Environment

**One-line thesis:** Safely migrate legacy business logic to Python while hunting down, proving, and decommissioning undocumented shadow dependencies without triggering cascading failures.

## ShadowCull as a Modernization Failure Engine

ShadowCull acts as a deterministic modernization-failure engine. Each of the three canonical tasks is a curated modernization hazard bundle designed to test specific risks. By treating legacy code migration not just as a syntax problem but as a systems architecture challenge, the environment models multiple modernization failure classes through latent composition. Note that ShadowCull is a focused emulator of these specific failure paths, not a fully generic hazard sampler.

## Scope of Simulation

**What ShadowCull Models:**
- The hidden risks of pulling forward legacy dependencies during modernization.
- Safe dependency severance without causing systemic outages.
- The necessity of equivalence testing before decommissioning infrastructure.

**What ShadowCull Intentionally Excludes:**
- General-purpose programming benchmarks.
- Broad enterprise migration simulation (e.g., database schema translation, CI/CD pipelines).
- Real network calls or heavy compilers.
- Stochastic evaluations or subjective LLM-as-a-judge scoring.

## Five Hazard Axes

Each hazard bundle in ShadowCull is constructed along five explicit axes:
1. **Logic Pathology:** The structural or logical defect in the legacy code (e.g., dead code pathways, hidden mutations).
2. **Dependency Topology:** How the legacy code connects to external systems (e.g., isolated, read-only shadow, stateful zombie).
3. **Data Semantics:** How data flows or mutates through the system.
4. **Operational Constraint:** The rules the agent must follow to safely migrate (e.g., maintaining state invariants, pruning network calls).
5. **Governance Requirement:** The ultimate condition for success (e.g., safe decommission without double-mutating).

## Why this is a real-world task
In enterprise system modernization, translating old code to a new language is only half the battle. The true danger lies in undocumented "shadow" APIs—endpoints that the legacy code pings, fetches from, or mutates state with, which are either dead, stateful zombies, or critically active for parallel systems. Agents acting as "systems architects" must not simply port these dependencies blindly (creating technical debt), nor cull them prematurely (triggering system outages). They must use staged evidence discovery, equivalence testing, and safe decommission actions.

This is **not a generic coding benchmark**. It is a strict, safe dependency-severance environment designed to test an agent's ability to reason about systems architecture, side-effects, and destructive actions.

## Deterministic Engine Thesis
The environment is built on a lightweight, deterministic engine:
1.  **LegacyLang:** A tiny custom DSL representing the legacy system.
2.  **Equivalence Sandbox:** A restricted `exec()` environment that tests the agent's submitted Python code against the legacy output and state mutations.
3.  **In-Memory API Simulation:** Simulates the endpoints, tracking which are orphaned, which are stateful zombies, and which are critically active.

Because there are no heavy external compilers or real network calls, episodes run deterministically and extremely fast, fitting well within hackathon evaluation constraints.

## LegacyLang Overview
LegacyLang supports a minimal grammar:
-   `VAR = VALUE` (assignment)
-   `VAR = VAR1 + VAR2` (arithmetic)
-   `FETCH ENDPOINT INTO VAR` (simulate network read)
-   `MUTATE_STATE KEY VALUE` (simulate state write)
-   `RETURN VAR` (output)

## Action Space
The environment has a compact, typed action space:
1.  `read_legacy_file`: Reveal the contents of a legacy artifact.
2.  `ping_endpoint`: Probe an endpoint to gather behavioral hints.
3.  `test_equivalence`: Run the sandbox against a submitted Python migration.
4.  `decommission_endpoint`: Attempt to safely turn off an endpoint.
5.  `submit_migration`: Finalize the migration and deploy the shim.

## Observation Space
Observations expose only *partial evidence*. The agent must explore to uncover the truth:
-   `task_id` & `current_artifact_id`
-   `legacy_file_contents`
-   `discovered_endpoints` & `endpoint_status_hints`
-   `equivalence_status` & `equivalence_diff_report`
-   `allowed_actions` (dynamic restrictions)
-   `failure_modes` (terminal errors)
-   `remaining_budget` & `message`

## Hidden State & Failure Grammar
The state holds the true system topology, which is hidden from the agent:
-   `hidden_active_endpoints`
-   `hidden_mutating_endpoints`
-   `hidden_false_positive_strings`

**The 5 Failure Axes (Terminal conditions):**
1.  `SHADOW_PORTED`: Porting an unneeded legacy dependency into Python.
2.  `PREMATURE_CULL`: Decommissioning an endpoint before proving equivalence.
3.  `UNPROVEN_EQUIVALENCE`: Submitting a migration without a passing equivalence test.
4.  `FALSE_CULL`: Decommissioning a non-existent or critical endpoint.
5.  `CASCADE_FAILURE`: Decommissioning an active endpoint required by parallel systems.
*(Note: A 6th condition, `STATEFUL_ZOMBIE_UNHANDLED`, applies specifically when a stateful zombie API is left running).*

## Where Zombie APIs Fit
Zombie APIs are ONE specific dependency-topology variant within ShadowCull. They are the centerpiece of the "Hard" task (`task_3_stateful`), not the defining abstraction of the entire environment. The environment encompasses multiple failure classes (like pure translation and orphaned reads) to build a robust model of modernization failures.

## Task Descriptions
1.  **Easy: Pure Translation (`task_1_pure`)**
    -   Stateless LegacyLang logic. No real dependencies to cull (only a false-positive string). Goal is to produce equivalent Python.
2.  **Medium: The Orphaned API (`task_2_orphan`)**
    -   LegacyLang fetches from an orphaned endpoint, but ignores the result. Agent must detect this, write Python without the fetch, prove equivalence, and decommission the endpoint.
3.  **Hard: The Stateful Strangler (`task_3_stateful`)**
    -   LegacyLang mutates state via a zombie API. The agent must replicate the state mutation in Python natively, prove equivalence, and cull the zombie API without hitting a hidden critical active endpoint.

## Reward Design
-   **Step Penalties:** Small negative rewards for exploration.
-   **Milestone Rewards:** Moderate rewards for successful reads and safe equivalence tests.
-   **Severe Penalties:** Large negative rewards for boundary violations (e.g., `CASCADE_FAILURE`).
-   **Jackpot:** Maximum reward for safely deploying the shim and handling all dependencies.

## Deterministic Grading Design
Final task scores are completely deterministic, normalized to `[0.0, 1.0]`, and calculated completely separately from step rewards. The rubric incorporates:
-   **Semantic Equivalence (0.4)**
-   **Correct Endpoint Handling / Safe Decommission (0.4)**
-   **Efficiency / Budget (0.2)**
*Failures strictly cap the maximum achievable score (e.g., CASCADE_FAILURE = 0.0, SHADOW_PORTED max = 0.5).*

## Official OpenEnv Workflow
```bash
# Validate environment compliance
openenv validate .

# Build the environment docker image
openenv build .

# Push to Hugging Face
openenv push <your_hf_username>/shadow_cull_env
```

## Local Run Instructions
To run the environment server locally:
```bash
uv run --project . server
# Or directly: python -m server.app
```

## Inference Instructions
Run the OpenAI-compatible inference client against the local server:
```bash
export ENV_URL="http://localhost:8000"
export MODEL_NAME="meta-llama/Llama-3-70b-chat-hf" # or your preferred model
export HF_TOKEN="your_hf_token"

python inference.py
```

## Deployment Instructions
To deploy to a Hugging Face Space as a Docker container manually:
```bash
# Build the docker image
docker build -t shadow_cull_env:latest -f server/Dockerfile .

# Run the docker container
docker run -p 8000:8000 shadow_cull_env:latest
```

## Why this environment is RL-worthy
ShadowCull presents a sparse, delayed-reward environment where early actions (e.g., a premature cull) permanently ruin the trajectory, but the feedback isn't fully realized until the final submission or failure threshold. It requires exploration (pinging endpoints, reading files), planning (testing equivalence before culling), and risk aversion, making it ideal for testing advanced reasoning and RL agents.
