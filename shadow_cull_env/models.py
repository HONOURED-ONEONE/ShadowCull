# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the Shadow Cull Env Environment.

This file defines the Action, Observation, and State schemas for the 
ShadowCull legacy migration and shadow dependency decommission environment.
"""

from enum import Enum
from typing import List, Dict, Optional

from openenv.core.env_server.types import Action, Observation, State
from pydantic import Field


class ActionType(str, Enum):
    READ_LEGACY_FILE = "read_legacy_file"
    PING_ENDPOINT = "ping_endpoint"
    TEST_EQUIVALENCE = "test_equivalence"
    DECOMMISSION_ENDPOINT = "decommission_endpoint"
    SUBMIT_MIGRATION = "submit_migration"


class ShadowCullAction(Action):
    """Action space for migrating legacy business logic safely."""
    
    action_type: ActionType = Field(
        ...,
        description="The type of action to perform."
    )
    target: Optional[str] = Field(
        default=None,
        description="The endpoint URL, file name, or target artifact for the action."
    )
    python_code: Optional[str] = Field(
        default=None,
        description="The submitted Python code (used in test_equivalence and submit_migration)."
    )


class ShadowCullObservation(Observation):
    """Observation containing partial evidence about the environment and endpoints."""
    
    task_id: str = Field(
        default="",
        description="Identifier for the current task (e.g., pure_translation, orphaned_api)."
    )
    current_artifact_id: Optional[str] = Field(
        default=None,
        description="The name or ID of the current legacy artifact being evaluated."
    )
    legacy_file_contents: Optional[str] = Field(
        default=None,
        description="The snippet or contents of the legacy file being read."
    )
    discovered_endpoints: List[str] = Field(
        default_factory=list,
        description="List of endpoints that have been discovered via pings or code analysis."
    )
    endpoint_status_hints: Dict[str, str] = Field(
        default_factory=dict,
        description="Hints or responses from pinged endpoints."
    )
    equivalence_status: str = Field(
        default="UNTESTED",
        description="Current state of semantic equivalence testing (e.g., PASS, FAIL, UNTESTED)."
    )
    equivalence_diff_report: Optional[str] = Field(
        default=None,
        description="Diff report showing mismatched output or state side-effects."
    )
    remaining_budget: int = Field(
        default=10,
        description="Number of steps remaining in the episode."
    )
    allowed_actions: List[str] = Field(
        default_factory=list,
        description="List of action types currently allowed."
    )
    failure_modes: List[str] = Field(
        default_factory=list,
        description="Current detected failure modes (e.g., SHADOW_PORTED, PREMATURE_CULL)."
    )
    message: str = Field(
        default="",
        description="System message detailing the result of the last action."
    )


class ShadowCullState(State):
    """Internal state holding the full topology, hidden truth, and grading metrics."""
    
    hidden_active_endpoints: List[str] = Field(
        default_factory=list,
        description="Actual live endpoints required by parallel systems."
    )
    hidden_mutating_endpoints: List[str] = Field(
        default_factory=list,
        description="Endpoints that modify global state and must not be called redundantly."
    )
    hidden_false_positive_strings: List[str] = Field(
        default_factory=list,
        description="Strings that might look like endpoints but are dead code."
    )
    safe_shim_deployed: bool = Field(
        default=False,
        description="Whether a safe shim has been successfully deployed."
    )
    shadow_dependency_ported: bool = Field(
        default=False,
        description="True if the agent ported an unneeded legacy dependency into Python."
    )
    cascading_failure: bool = Field(
        default=False,
        description="True if the agent wrongly decommissioned an actively used endpoint."
    )
    semantic_equivalence_score: float = Field(
        default=0.0,
        description="Running score of testing equivalence. 1.0 means perfectly equivalent."
    )
    budget_remaining: int = Field(
        default=10,
        description="Internal count of steps remaining before episode timeout."
    )
    transition_history: List[str] = Field(
        default_factory=list,
        description="Log of transitions for debugging and deterministic replay."
    )
    task_difficulty: str = Field(
        default="EASY",
        description="Difficulty level of the current task."
    )
    truth_type: str = Field(
        default="",
        description="The specific type of the hidden task truth."
    )
