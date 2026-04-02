TASK_HARD_STATEFUL = {
    "task_id": "hard_stateful_strangler",
    "difficulty": "HARD",
    "truth_type": "stateful_zombie",
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