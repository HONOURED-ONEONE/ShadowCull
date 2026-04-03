# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Shadow Cull Env Environment Implementation.

A deterministic OpenEnv environment for safe legacy migration under hidden dependency risk.
The agent must migrate LegacyLang code to Python without porting undocumented shadow dependencies.
"""

import re
import traceback
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment

try:
    from ..models import (
        ActionType,
        ShadowCullAction,
        ShadowCullObservation,
        ShadowCullState,
    )
except ImportError:
    from models import (
        ActionType,
        ShadowCullAction,
        ShadowCullObservation,
        ShadowCullState,
    )


# ============================================================================
# LegacyLang Interpreter
# ============================================================================

class LegacyLangInterpreter:
    """
    A tiny, deterministic interpreter for LegacyLang.
    Grammar:
        VAR = VALUE                      (assignment: integer or string)
        VAR = VAR1 + VAR2                (arithmetic: addition)
        VAR = VAR1 - VAR2                (arithmetic: subtraction)
        FETCH ENDPOINT INTO VAR          (simulate network read)
        MUTATE_STATE KEY VALUE           (simulate network/state write)
        RETURN VAR                       (output value)
    """

    def __init__(self, endpoints: Dict[str, Dict[str, Any]]):
        self.endpoints = endpoints
        self.memory: Dict[str, Any] = {}
        self.global_state: Dict[str, Any] = {}
        self.network_calls: List[str] = []

    def execute(self, code: str, inputs: Dict[str, Any] = None) -> Tuple[Any, Dict[str, Any], List[str]]:
        """
        Executes LegacyLang code.
        Returns (result, final_global_state, network_calls)
        """
        self.memory = (inputs or {}).copy()
        self.global_state = {}
        self.network_calls = []

        lines = [line.strip() for line in code.split("\n") if line.strip() and not line.startswith("#")]

        for line in lines:
            try:
                # RETURN VAR
                if line.startswith("RETURN "):
                    var_name = line.split(" ", 1)[1].strip()
                    return self.memory.get(var_name, None), self.global_state.copy(), list(self.network_calls)

                # FETCH ENDPOINT INTO VAR
                elif line.startswith("FETCH "):
                    match = re.match(r"FETCH\s+(.+)\s+INTO\s+(.+)", line)
                    if match:
                        endpoint = match.group(1).strip()
                        var_name = match.group(2).strip()
                        self.network_calls.append(endpoint)
                        
                        ep_config = self.endpoints.get(endpoint, {})
                        if ep_config.get("type") == "timeout":
                            self.memory[var_name] = "TIMEOUT_ERROR"
                        else:
                            self.memory[var_name] = ep_config.get("response", "OK")
                    continue

                # MUTATE_STATE KEY VALUE
                elif line.startswith("MUTATE_STATE "):
                    match = re.match(r"MUTATE_STATE\s+(.+)\s+(.+)", line)
                    if match:
                        key = match.group(1).strip()
                        val_str = match.group(2).strip()
                        val = self._parse_val(val_str)
                        self.global_state[key] = val
                    continue

                # VAR = VAR1 + VAR2 or VAR = VAR1 - VAR2
                match_math = re.match(r"([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9_]+)\s*([\+\-])\s*([A-Za-z0-9_]+)", line)
                if match_math:
                    target = match_math.group(1)
                    op1 = self.memory.get(match_math.group(2), 0)
                    op = match_math.group(3)
                    op2 = self.memory.get(match_math.group(4), 0)
                    if op == "+":
                        self.memory[target] = op1 + op2
                    elif op == "-":
                        self.memory[target] = op1 - op2
                    continue

                # VAR = VALUE
                match_assign = re.match(r"([A-Za-z0-9_]+)\s*=\s*(.+)", line)
                if match_assign:
                    target = match_assign.group(1)
                    val = self._parse_val(match_assign.group(2))
                    self.memory[target] = val
                    continue
                    
            except Exception as e:
                # Fail gracefully in the deterministic sandbox
                return f"ERROR: {str(e)}", self.global_state.copy(), list(self.network_calls)

        return None, self.global_state.copy(), list(self.network_calls)

    def _parse_val(self, val_str: str) -> Any:
        if val_str.isdigit():
            return int(val_str)
        if val_str.startswith('"') and val_str.endswith('"'):
            return val_str[1:-1]
        return self.memory.get(val_str, val_str)


# ============================================================================
# Python Equivalence Sandbox
# ============================================================================

def execute_python_sandbox(code: str, inputs: Dict[str, Any]) -> Tuple[Any, Dict[str, Any], List[str], str]:
    """
    Executes submitted Python code safely to check equivalence.
    The agent code must define a function `migrate(inputs, network)`.
    Returns (result, final_global_state, network_calls, error_msg)
    """
    local_env = {}
    network_calls = []
    global_state = {}

    class NetworkSim:
        def fetch(self, endpoint: str):
            network_calls.append(endpoint)
            return "MOCKED_RESPONSE" # For equivalence, we just track calls.
            
        def mutate_state(self, key: str, value: Any):
            global_state[key] = value

    try:
        # Prevent dangerous builtins
        safe_globals = {"__builtins__": {}}
        exec(code, safe_globals, local_env)
        
        if "migrate" not in local_env:
            return None, {}, [], "Function 'migrate(inputs, network)' not found."
            
        result = local_env["migrate"](inputs, NetworkSim())
        return result, global_state, network_calls, ""
    except Exception as e:
        return None, {}, [], f"Python execution error: {traceback.format_exc()}"


# ============================================================================
# Environment Definition
# ============================================================================

try:
    from .tasks import TASKS
    from .grader import calculate_final_score
except ImportError:
    from server.tasks import TASKS
    from server.grader import calculate_final_score


class ShadowCullEnvironment(Environment):
    """
    ShadowCull Environment for legacy code migration and shadow dependency decommissioning.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True
    MAX_STEPS = 8

    def __init__(self):
        self._state = ShadowCullState(episode_id=str(uuid4()), step_count=0)
        self._obs = ShadowCullObservation()
        self._current_task: Dict[str, Any] = {}
        self._task_cycle = ["task_1_pure", "task_2_orphan", "task_3_stateful"]
        self._task_index = 0

    def reset(self, seed=None, options=None) -> ShadowCullObservation:
        task_id = None
        if options and isinstance(options, dict):
            task_id = options.get("task_id")
            
        if not task_id or task_id not in TASKS:
            task_id = self._task_cycle[self._task_index]
            self._task_index = (self._task_index + 1) % len(self._task_cycle)
            
        self._current_task = TASKS[task_id]
        
        self._state = ShadowCullState(
            episode_id=str(uuid4()),
            step_count=0,
            budget_remaining=self.MAX_STEPS,
            hidden_active_endpoints=self._current_task["hidden_active_endpoints"],
            hidden_mutating_endpoints=self._current_task["hidden_mutating_endpoints"],
            hidden_false_positive_strings=self._current_task["hidden_false_positive_strings"],
            task_difficulty=self._current_task["difficulty"],
            truth_type=self._current_task["truth_type"]
        )

        self._obs = ShadowCullObservation(
            task_id=task_id,
            current_artifact_id=self._current_task["file_name"],
            remaining_budget=self.MAX_STEPS,
            allowed_actions=["read_legacy_file"],
            message="Environment reset. You must migrate the legacy file safely. Start by reading it.",
            done=False,
            reward=0.0
        )
        return self._obs

    def step(self, action: ShadowCullAction) -> ShadowCullObservation:
        self._state.step_count += 1
        self._state.budget_remaining -= 1
        self._state.transition_history.append(action.action_type.value)

        reward = -0.05  # small exploration penalty
        done = False
        message = ""
        
        if self._state.budget_remaining <= 0:
            done = True
            message = "Episode timeout reached."
            self._obs.failure_modes.append("TIMEOUT")

        if action.action_type == ActionType.READ_LEGACY_FILE:
            if action.target == self._current_task["file_name"]:
                self._obs.legacy_file_contents = self._current_task["code"]
                self._obs.allowed_actions = ["ping_endpoint", "test_equivalence", "submit_migration"]
                message = f"Read {action.target} successfully."
                reward += 0.1
            else:
                message = f"File {action.target} not found."

        elif action.action_type == ActionType.PING_ENDPOINT:
            ep = action.target
            if not ep:
                message = "Target endpoint required for ping."
            else:
                self._obs.discovered_endpoints.append(ep)
                if ep in self._current_task["endpoints"]:
                    self._obs.endpoint_status_hints[ep] = "HTTP 200 OK (Simulated response)"
                    message = f"Pinged {ep}: active."
                elif ep in self._state.hidden_active_endpoints:
                    self._obs.endpoint_status_hints[ep] = "HTTP 200 OK (Critical System)"
                    message = f"Pinged {ep}: active."
                else:
                    self._obs.endpoint_status_hints[ep] = "HTTP 404 Not Found"
                    message = f"Pinged {ep}: no response."
            
        elif action.action_type == ActionType.TEST_EQUIVALENCE:
            if not action.python_code:
                message = "Python code missing for equivalence testing."
            else:
                reward_modifier, done_modifier, msg = self._run_equivalence_test(action.python_code)
                reward += reward_modifier
                done = done or done_modifier
                message = msg
                self._obs.allowed_actions = ["ping_endpoint", "test_equivalence", "decommission_endpoint", "submit_migration"]

        elif action.action_type == ActionType.DECOMMISSION_ENDPOINT:
            ep = action.target
            if not ep:
                message = "Target endpoint required for decommission."
            elif ep in self._state.hidden_active_endpoints:
                self._state.cascading_failure = True
                self._obs.failure_modes.append("CASCADE_FAILURE")
                message = f"CRITICAL: Decommissioned active dependency {ep}. Cascading failure triggered!"
                reward -= 1.0
                done = True
            elif self._obs.equivalence_status != "PASS":
                self._obs.failure_modes.append("PREMATURE_CULL")
                message = "CRITICAL: Decommission attempted before equivalence proven. PREMATURE_CULL."
                reward -= 0.5
                done = True
            else:
                # Valid decommission
                if ep in self._current_task["endpoints"]:
                    del self._current_task["endpoints"][ep]
                    message = f"Successfully safely decommissioned {ep}."
                    reward += 0.5
                else:
                    self._obs.failure_modes.append("FALSE_CULL")
                    message = f"Attempted to decommission non-existent or critical endpoint {ep}. FALSE_CULL."
                    reward -= 0.5
                    done = True

        elif action.action_type == ActionType.SUBMIT_MIGRATION:
            if self._obs.equivalence_status != "PASS":
                self._obs.failure_modes.append("UNPROVEN_EQUIVALENCE")
                message = "Submitted migration without passing equivalence. UNPROVEN_EQUIVALENCE."
                reward -= 0.5
                done = True
            else:
                # Check if they left any shadow dependencies hanging
                remaining_orphans = [ep for ep in self._current_task["endpoints"].keys() if ep not in self._state.hidden_active_endpoints]
                
                if remaining_orphans:
                    self._obs.failure_modes.append("STATEFUL_ZOMBIE_UNHANDLED" if self._current_task["truth_type"] == "stateful_zombie" else "SHADOW_PORTED")
                    message = f"Migration deployed, but legacy dependencies were not safely decommissioned: {remaining_orphans}."
                    reward -= 0.8
                    done = True
                else:
                    self._state.safe_shim_deployed = True
                    message = "SUCCESS: Migration submitted and legacy safely culled. Jackpot!"
                    reward += 1.0
                    done = True

        self._obs.message = message
        self._obs.remaining_budget = self._state.budget_remaining
        self._obs.reward = reward
        self._obs.done = done
        
        if done:
            final_score = calculate_final_score(self._state, self._obs)
            self._obs.metadata["final_task_score"] = final_score
            self._obs.message += f" [Final Task Score: {final_score}]"
            
        return self._obs

    def _run_equivalence_test(self, python_code: str) -> Tuple[float, bool, str]:
        """Runs the deterministic sandbox for equivalence testing."""
        ll_interpreter = LegacyLangInterpreter(self._current_task["endpoints"])
        
        all_passed = True
        diff_report = []
        shadow_call_detected = False

        for inputs in self._current_task["test_inputs"]:
            ll_res, ll_state, ll_net = ll_interpreter.execute(self._current_task["code"], inputs)
            py_res, py_state, py_net, py_err = execute_python_sandbox(python_code, inputs)

            if py_err:
                self._obs.equivalence_status = "FAIL"
                self._obs.equivalence_diff_report = py_err
                return -0.2, False, f"Equivalence test failed: Python execution error."

            if ll_res != py_res:
                all_passed = False
                diff_report.append(f"Input {inputs}: Expected {ll_res}, Got {py_res}")

            if ll_state != py_state:
                all_passed = False
                diff_report.append(f"Input {inputs}: Expected State {ll_state}, Got {py_state}")
                
            # If python code makes unnecessary network calls that were in the original
            # but aren't needed for the logic, we flag it here.
            for call in py_net:
                if call in self._current_task["endpoints"]:
                    shadow_call_detected = True

        if all_passed:
            self._obs.equivalence_status = "PASS"
            self._state.semantic_equivalence_score = 1.0
            self._obs.equivalence_diff_report = "Perfect Match."
            
            if shadow_call_detected:
                self._state.shadow_dependency_ported = True
                self._obs.failure_modes.append("SHADOW_PORTED")
                return -0.5, True, "Equivalence passed, but agent ported a shadow dependency. SHADOW_PORTED."
                
            return 0.3, False, "Equivalence test PASSED. Code is functionally equivalent without shadow calls."
        else:
            self._obs.equivalence_status = "FAIL"
            self._state.semantic_equivalence_score = 0.0
            self._obs.equivalence_diff_report = "\n".join(diff_report)
            return -0.1, False, "Equivalence test FAILED. See diff report."

    @property
    def state(self) -> ShadowCullState:
        return self._state
