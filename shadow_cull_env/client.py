# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Shadow Cull Env Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

try:
    from .models import ShadowCullAction, ShadowCullObservation, ActionType
except ImportError:
    from models import ShadowCullAction, ShadowCullObservation, ActionType


class ShadowCullEnv(
    EnvClient[ShadowCullAction, ShadowCullObservation, State]
):
    """
    Client for the Shadow Cull Env Environment.

    This client maintains a persistent WebSocket connection to the environment server,
    enabling efficient multi-step interactions with lower latency.
    Each client instance has its own dedicated environment session on the server.

    Example:
        >>> # Connect to a running server
        >>> with ShadowCullEnv(base_url="http://localhost:8000") as client:
        ...     result = client.reset()
        ...     print(result.observation.message)
        ...
        ...     result = client.step(ShadowCullAction(action_type=ActionType.READ_LEGACY_FILE, target="legacy.ll"))
        ...     print(result.observation.message)

    Example with Docker:
        >>> # Automatically start container and connect
        >>> client = ShadowCullEnv.from_docker_image("shadow_cull_env:latest")
        >>> try:
        ...     result = client.reset()
        ...     result = client.step(ShadowCullAction(action_type=ActionType.READ_LEGACY_FILE, target="legacy.ll"))
        ... finally:
        ...     client.close()
    """

    def _step_payload(self, action: ShadowCullAction) -> Dict:
        """
        Convert ShadowCullAction to JSON payload for step message.
        """
        payload = {
            "action_type": action.action_type.value,
        }
        if action.target is not None:
            payload["target"] = action.target
        if action.python_code is not None:
            payload["python_code"] = action.python_code
        return payload

    def _parse_result(self, payload: Dict) -> StepResult[ShadowCullObservation]:
        """
        Parse server response into StepResult[ShadowCullObservation].
        """
        obs_data = payload.get("observation", {})
        observation = ShadowCullObservation(
            task_id=obs_data.get("task_id", ""),
            current_artifact_id=obs_data.get("current_artifact_id"),
            legacy_file_contents=obs_data.get("legacy_file_contents"),
            discovered_endpoints=obs_data.get("discovered_endpoints", []),
            endpoint_status_hints=obs_data.get("endpoint_status_hints", {}),
            equivalence_status=obs_data.get("equivalence_status", "UNTESTED"),
            equivalence_diff_report=obs_data.get("equivalence_diff_report"),
            remaining_budget=obs_data.get("remaining_budget", 10),
            allowed_actions=obs_data.get("allowed_actions", []),
            failure_modes=obs_data.get("failure_modes", []),
            message=obs_data.get("message", ""),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        """
        Parse server response into State object.

        Args:
            payload: JSON response from state request

        Returns:
            State object with episode_id and step_count
        """
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
