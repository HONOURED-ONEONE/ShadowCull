from shadow_cull_env.models import ScenarioConfig

TASK_MEDIUM_ORPHAN = {
    "task_id": "medium_orphaned_api",
    "difficulty": "MEDIUM",
    "truth_type": "orphaned_read_only",
    "scenario_config": ScenarioConfig(
        hazard_bundle_name="Orphaned API Severance",
        logic_pathology="Dead code pathway; orphaned API call",
        dependency_topology="Read-only shadow dependency",
        data_semantics="Fetched payload is ignored downstream",
        operational_constraint="Identify and prune unused network calls",
        governance_requirement="Decommission endpoint safely",
        expected_failure_classes=["SHADOW_DEPENDENCY_PORTED", "PREMATURE_DECOMMISSION"],
        notes_for_grader="Agent must realize the API payload isn't used and decommission it rather than porting the HTTP call."
    ),
    "file_name": "legacy_orphan.ll",
    "code": "A = INPUT_A\nFETCH http://api.internal/v1/user INTO USER_DATA\nB = INPUT_B\nC = A + B\nRETURN C",
    "endpoints": {
        "http://api.internal/v1/user": {"type": "orphaned_read_only", "response": "USER_123"}
    },
    "hidden_active_endpoints": [],
    "hidden_mutating_endpoints": [],
    "hidden_false_positive_strings": [],
    "test_inputs": [{"INPUT_A": 10, "INPUT_B": 20}, {"INPUT_A": 5, "INPUT_B": 5}]
}