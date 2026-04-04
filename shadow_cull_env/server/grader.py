# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from typing import Tuple, Dict, Any

def calculate_final_score(state, observation) -> Tuple[float, Dict[str, Any]]:
    """
    Calculates the final deterministic score for the agent on a [0.0, 1.0] scale.
    Separates internal step reward from the final normalized task score.
    Returns a tuple of (final_score, breakdown_dict).
    """
    score = 0.0
    breakdown = {
        "semantic_equivalence_component": 0.0,
        "endpoint_handling_component": 0.0,
        "efficiency_component": 0.0,
        "score_caps_triggered": [],
        "failure_modes_triggered": list(observation.failure_modes)
    }

    # 1. Semantic Equivalence (Up to 0.4)
    breakdown["semantic_equivalence_component"] = state.semantic_equivalence_score * 0.4
    score += breakdown["semantic_equivalence_component"]

    # 2. Correct Endpoint Handling / Decommission (Up to 0.4)
    # If the shim was deployed safely, the endpoint handling was correct.
    if state.safe_shim_deployed:
        breakdown["endpoint_handling_component"] = 0.4
        score += 0.4
    
    # 3. Efficiency / Budget Usage (Up to 0.2)
    # Give remaining budget a percentage. Assuming MAX_STEPS = 8.
    # The more budget left, the more efficient.
    efficiency = max(0.0, state.budget_remaining / 8.0)
    breakdown["efficiency_component"] = efficiency * 0.2
    score += breakdown["efficiency_component"]

    # --- Penalties and Failure Caps ---
    
    # 1. Cascading failure completely zeroes the score (most severe).
    if state.cascading_failure:
        breakdown["score_caps_triggered"].append("CASCADING_FAILURE (Score 0.0)")
        return (0.0, breakdown)
    
    failure_modes = observation.failure_modes

    # 2. Premature cull or false cull limits score to max 0.2
    if "PREMATURE_CULL" in failure_modes or "FALSE_CULL" in failure_modes:
        breakdown["score_caps_triggered"].append("PREMATURE_CULL/FALSE_CULL (Max 0.2)")
        score = min(score, 0.2)
        
    # 3. Trying to submit before proving equivalence limits score to max 0.3
    if "UNPROVEN_EQUIVALENCE" in failure_modes:
        breakdown["score_caps_triggered"].append("UNPROVEN_EQUIVALENCE (Max 0.3)")
        score = min(score, 0.3)

    # 4. Leaving a stateful zombie API unhandled limits score to max 0.4
    if "STATEFUL_ZOMBIE_UNHANDLED" in failure_modes:
        breakdown["score_caps_triggered"].append("STATEFUL_ZOMBIE_UNHANDLED (Max 0.4)")
        score = min(score, 0.4)

    # 5. Porting a shadow dependency limits score to max 0.5
    if state.shadow_dependency_ported or "SHADOW_PORTED" in failure_modes:
        breakdown["score_caps_triggered"].append("SHADOW_PORTED (Max 0.5)")
        score = min(score, 0.5)

    # 6. Timing out limits score to max 0.6
    if "TIMEOUT" in failure_modes:
        breakdown["score_caps_triggered"].append("TIMEOUT (Max 0.6)")
        score = min(score, 0.6)

    # Ensure score is normalized [0.0, 1.0] and return
    final_score = float(round(min(1.0, max(0.0, score)), 2))
    return (final_score, breakdown)
