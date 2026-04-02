TASK_MEDIUM_ORPHAN = {
    "task_id": "medium_orphaned_api",
    "difficulty": "MEDIUM",
    "truth_type": "orphaned_read_only",
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