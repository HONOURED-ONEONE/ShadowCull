# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

def calculate_final_score(state, observation) -> float:
    """
    Calculates the final deterministic score for the agent on a [0.0, 1.0] scale.
    Separates internal step reward from the final normalized task score.
    """
    score = 0.0

    # 1. Semantic Equivalence (Up to 0.4)
    score += state.semantic_equivalence_score * 0.4

    # 2. Correct Endpoint Handling / Decommission (Up to 0.4)
    # If the shim was deployed safely, the endpoint handling was correct.
    if state.safe_shim_deployed:
        score += 0.4
    
    # 3. Efficiency / Budget Usage (Up to 0.2)
    # Give remaining budget a percentage. Assuming MAX_STEPS = 8.
    # The more budget left, the more efficient.
    efficiency = max(0.0, state.budget_remaining / 8.0)
    score += efficiency * 0.2

    # --- Penalties and Failure Caps ---
    
    # 1. Cascading failure completely zeroes the score (most severe).
    if state.cascading_failure:
        return 0.0
    
    failure_modes = observation.failure_modes

    # 2. Premature cull or false cull limits score to max 0.2
    if "PREMATURE_CULL" in failure_modes or "FALSE_CULL" in failure_modes:
        score = min(score, 0.2)
        
    # 3. Trying to submit before proving equivalence limits score to max 0.3
    if "UNPROVEN_EQUIVALENCE" in failure_modes:
        score = min(score, 0.3)

    # 4. Leaving a stateful zombie API unhandled limits score to max 0.4
    if "STATEFUL_ZOMBIE_UNHANDLED" in failure_modes:
        score = min(score, 0.4)

    # 5. Porting a shadow dependency limits score to max 0.5
    if state.shadow_dependency_ported or "SHADOW_PORTED" in failure_modes:
        score = min(score, 0.5)

    # 6. Timing out limits score to max 0.6
    if "TIMEOUT" in failure_modes:
        score = min(score, 0.6)

    # Ensure score is normalized [0.0, 1.0] and return
    return float(round(min(1.0, max(0.0, score)), 2))
