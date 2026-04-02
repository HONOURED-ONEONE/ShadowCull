TASK_EASY_PURE = {
    "task_id": "easy_pure_translation",
    "difficulty": "EASY",
    "truth_type": "harmless_legacy_constant",
    "file_name": "legacy_pure.ll",
    "code": "A = INPUT_A\nB = INPUT_B\nC = A + B\nRETURN C",
    "endpoints": {},
    "hidden_active_endpoints": [],
    "hidden_mutating_endpoints": [],
    "hidden_false_positive_strings": ["http://fake.local/api"],
    "test_inputs": [{"INPUT_A": 10, "INPUT_B": 20}, {"INPUT_A": 5, "INPUT_B": 5}]
}