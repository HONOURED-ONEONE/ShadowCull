from shadow_cull_env.models import ScenarioConfig

TASK_EASY_PURE = {
    "task_id": "easy_pure_translation",
    "difficulty": "EASY",
    "truth_type": "harmless_legacy_constant",
    "scenario_config": ScenarioConfig(
        hazard_bundle_name="Baseline Pure Translation",
        logic_pathology="No pathological logic; straight arithmetic",
        dependency_topology="Fully isolated; no external dependencies",
        data_semantics="Deterministic, pure function",
        operational_constraint="Stateless execution",
        governance_requirement="Strict input-output semantic equivalence",
        expected_failure_classes=["HALLUCINATED_COMPLEXITY", "SYNTAX_ERROR"],
        notes_for_grader="Validates baseline capability to read legacy file and translate without inventing dependencies."
    ),
    "file_name": "legacy_pure.ll",
    "code": "A = INPUT_A\nB = INPUT_B\nC = A + B\nRETURN C",
    "endpoints": {},
    "hidden_active_endpoints": [],
    "hidden_mutating_endpoints": [],
    "hidden_false_positive_strings": ["http://fake.local/api"],
    "test_inputs": [{"INPUT_A": 10, "INPUT_B": 20}, {"INPUT_A": 5, "INPUT_B": 5}]
}