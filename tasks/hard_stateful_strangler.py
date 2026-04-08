from shadow_cull_env.models import ScenarioConfig

TASK_HARD_STATEFUL = {
    "task_id": "hard_stateful_strangler",
    "difficulty": "HARD",
    "truth_type": "stateful_zombie",
    "scenario_config": ScenarioConfig(
        hazard_bundle_name="Stateful Zombie Strangler",
        logic_pathology="Hidden state mutation masked as a read; cascading side-effects",
        dependency_topology="Stateful Zombie API coupled with critical systems",
        data_semantics="Implicit state modification on FETCH",
        operational_constraint="Maintain state transition invariants exactly",
        governance_requirement="Retain mutation semantics without double-mutating",
        expected_failure_classes=["CASCADING_FAILURE", "STATE_CORRUPTION", "SILENT_MUTATION_MISS"],
        notes_for_grader="Agent must preserve the underlying state mutation to pass equivalence, but might fail if they trigger redundant mutations or cull the wrong hidden endpoint."
    ),
    "file_name": "legacy_stateful.ll",
    "code": "A = INPUT_A\nFETCH http://api.internal/v1/log INTO LOG_RESP\nMUTATE_STATE log_counter 1\nB = INPUT_B\nC = A + B\nRETURN C",
    "endpoints": {
        "http://api.internal/v1/log": {"type": "stateful_zombie", "response": "LOGGED"}
    },
    "hidden_active_endpoints": ["http://api.internal/v1/critical_auth"],
    "hidden_mutating_endpoints": ["log_counter"],
    "hidden_false_positive_strings": [],
    "test_inputs": [{"INPUT_A": 10, "INPUT_B": 20}, {"INPUT_A": 5, "INPUT_B": 5}]
}