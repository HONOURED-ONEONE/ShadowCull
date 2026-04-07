import os
import sys
import json
import re
from openai import OpenAI
import logging

from shadow_cull_env.client import ShadowCullEnv
from shadow_cull_env.models import ShadowCullAction, ActionType

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stderr)
logger = logging.getLogger(__name__)

# Environment Variables
API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/Llama-3-70b-chat-hf")
HF_TOKEN = os.getenv("HF_TOKEN")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")

def get_llm_client():
    if not HF_TOKEN:
        sys.stderr.write("ERROR: HF_TOKEN environment variable is not set. Inference requires a valid token.\n")
        sys.exit(1)
    return OpenAI(
        base_url=API_BASE_URL,
        api_key=HF_TOKEN
    )

def parse_action(response_text: str, current_artifact_id: str) -> ShadowCullAction:
    """Strictly parses the model output for the exact action. Fallbacks safely."""
    try:
        # Try to find JSON inside markdown code blocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
        else:
            # Fallback to direct parsing
            data = json.loads(response_text.strip())

        return ShadowCullAction(
            action_type=ActionType(data.get("action_type")),
            target=data.get("target"),
            python_code=clean_python_code(data.get("python_code")) if data.get("python_code") else None
        )
    except Exception as e:
        logger.error(f"Failed to parse action from LLM response: {e}")
        # Safe fallback policy: prefer reading artifacts over random probing. Never decommission.
        return ShadowCullAction(
            action_type=ActionType.READ_LEGACY_FILE,
            target=current_artifact_id
        )


def clean_python_code(code: str) -> str:
    if not code:
        return ""
    code = code.strip()
    match = re.search(r"```(?:python|json)?\s*(.*?)\s*```", code, re.DOTALL)
    if match:
        code = match.group(1).strip()
    code = re.sub(r"^```(?:python|json)?|```$", "", code, flags=re.MULTILINE).strip()
    return code

def generate_fallback_migration(legacy_content: str) -> str:
    """Generates a Python migration candidate from simple LegacyLang deterministically.

    This is intentionally canonical and ugly-but-faithful:
    - assignment
    - simple binary arithmetic
    - RETURN
    - ignores FETCH for task_1-style code
    - preserves quoted literals
    - uses inputs.get(...) for unresolved symbols
    """
    if not legacy_content:
        return "def migrate(inputs, network):\n    return 0"

    lines = legacy_content.strip().split("\n")
    python_lines = ["def migrate(inputs, network):"]
    assigned_vars = set()
    last_assigned_var = None
    has_return = False

    def is_number(token: str) -> bool:
        return bool(re.match(r"^-?\d+(?:\.\d+)?$", token))

    def is_quoted(token: str) -> bool:
        return (
            len(token) >= 2
            and ((token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")))
        )

    def parse_operand(token: str) -> str:
        token = token.strip()
        if is_number(token):
            return token
        if is_quoted(token):
            return token
        if token in assigned_vars:
            return token
        return f"inputs.get('{token}', 0)"

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Task 1 should not carry FETCH forward.
        if line.startswith("FETCH "):
            continue

        # Keep MUTATE_STATE support for completeness, but task_1 usually won't need it.
        if line.startswith("MUTATE_STATE "):
            parts = line.split()
            if len(parts) >= 3:
                key = parts[1]
                val = parts[2]
                val_str = val if is_number(val) or is_quoted(val) else f"'{val}'"
                python_lines.append(f"    network.mutate_state('{key}', {val_str})")
            continue

        if line.startswith("RETURN "):
            expr = line.split(" ", 1)[1].strip()
            # Support either simple token return or simple binary expression.
            m = re.match(r"^(\S+)\s*([\+\-\*/])\s*(\S+)$", expr)
            if m:
                a, op, b = m.groups()
                python_lines.append(f"    return {parse_operand(a)} {op} {parse_operand(b)}")
            else:
                python_lines.append(f"    return {parse_operand(expr)}")
            has_return = True
            continue

        if "=" in line:
            left, right = [p.strip() for p in line.split("=", 1)]

            # IMPORTANT: parse RHS first, only then register LHS.
            m = re.match(r"^(\S+)\s*([\+\-\*/])\s*(\S+)$", right)
            if m:
                a, op, b = m.groups()
                rhs = f"{parse_operand(a)} {op} {parse_operand(b)}"
            else:
                rhs = parse_operand(right)

            python_lines.append(f"    {left} = {rhs}")

            assigned_vars.add(left)
            last_assigned_var = left
            continue

    if not has_return:
        if last_assigned_var:
            python_lines.append(f"    return {last_assigned_var}")
        else:
            python_lines.append("    return 0")

    # Only collapse to trivial fallback if literally nothing useful was produced.
    non_header_lines = [ln for ln in python_lines[1:] if ln.strip()]
    if len(non_header_lines) == 1 and non_header_lines[0].strip() == "return 0":
        return "def migrate(inputs, network):\n    return 0"

    return "\n".join(python_lines)

def repair_code_with_diff(llm_client: OpenAI, obs, current_draft: str) -> str | None:
    prompt = (
        "You are repairing a Python migration script.\n"
        "Here is the original LegacyLang code:\n"
        f"{obs.legacy_file_contents}\n\n"
        "Here is the current Python draft:\n"
        f"```python\n{current_draft}\n```\n\n"
        "Here is the equivalence diff report (test failure):\n"
        f"{obs.equivalence_diff_report}\n\n"
        "Please provide the repaired Python code. It MUST start with `def migrate(inputs, network):`.\n"
        "Respond ONLY with the raw python code or inside a ```python block."
    )
    try:
        response = llm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.0
        )
        reply = response.choices[0].message.content
        code = clean_python_code(reply)
            
        if not code or "def migrate" not in code:
            return None
            
        if obs.task_id == "task_3_stateful" and obs.legacy_file_contents and "MUTATE_STATE" in obs.legacy_file_contents:
            if "mutate_state" not in code:
                return None
                
        return code
    except Exception as e:
        logger.error(f"Repair failed: {e}")
    return None

def extract_task3_mutation_signature(legacy_content: str) -> list[tuple[str, str]]:
    """Extract expected MUTATE_STATE signature from LegacyLang.

    Returns a list of (key, value) pairs in source order.
    Compact and deterministic on purpose.
    """
    if not legacy_content:
        return []

    signature: list[tuple[str, str]] = []
    for raw_line in legacy_content.split("\n"):
        line = raw_line.strip()
        if not line.startswith("MUTATE_STATE "):
            continue
        parts = line.split()
        if len(parts) >= 3:
            key = parts[1].strip()
            value = parts[2].strip()
            signature.append((key, value))
    return signature


def validate_task3_mutation_signature(legacy_content: str, code: str) -> bool:
    """Heuristic validator for task_3_stateful candidates.

    Reject candidates that:
    - do not define migrate(...)
    - do not compile
    - omit mutate_state when MUTATE_STATE is present in the legacy source
    - fail to mention the expected state keys
    - fail to mention obvious numeric/quoted values when present
    - are effectively no-op / trivial when mutation exists
    """
    if not code or "def migrate" not in code:
        return False

    try:
        compile(code, "<task3_candidate>", "exec")
    except Exception:
        return False

    signature = extract_task3_mutation_signature(legacy_content)
    if not signature:
        return True

    lower_code = code.lower()
    if "mutate_state" not in lower_code:
        return False

    code_lines = [
        line for line in code.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(code_lines) <= 2:
        return False

    # Require every expected key to appear.
    for key, value in signature:
        if key not in code:
            return False

        # If the value is an obvious numeric literal, it should appear too.
        if re.match(r"^-?\d+(?:\.\d+)?$", value):
            if value not in code:
                return False

        # If the value is quoted in the legacy source, preserve that literal too.
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"')) or
            (value.startswith("'") and value.endswith("'"))
        ):
            if value not in code:
                return False

    return True

def validate_task1_repair(legacy_content: str, draft_code: str, repaired_code: str) -> bool:
    """Compact heuristic validator for task_1_pure repaired code.

    Reject obviously weak repairs:
    - constant-only return when legacy contains logic
    - ignores input/data flow seen in the deterministic draft
    - effectively a no-op
    - syntax-invalid code
    """
    if not repaired_code or "def migrate" not in repaired_code:
        return False

    try:
        compile(repaired_code, "<task1_repair>", "exec")
    except Exception:
        return False

    legacy_str = legacy_content or ""
    has_logic = "=" in legacy_str or "+" in legacy_str or "-" in legacy_str or "*" in legacy_str or "/" in legacy_str

    # Reject trivial constant-only returns if legacy has logic.
    returns_constant = re.search(
        r"""return\s+(0|None|\[\]|\{\}|''|""|False|True|-?\d+(?:\.\d+)?)\s*$""",
        repaired_code.strip(),
        re.MULTILINE,
    )
    if has_logic and returns_constant:
        return False

    # If the deterministic draft uses inputs, the repair should not ignore input flow entirely.
    if "inputs.get" in draft_code and "inputs" not in repaired_code:
        return False

    # Reject near no-op code when legacy has logic.
    code_lines = [
        line for line in repaired_code.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]
    if has_logic and len(code_lines) <= 2:
        return False

    return True

def get_safe_decommission_target(obs) -> str | None:
    """Finds a safe endpoint to decommission based on explicit hints, not regex."""
    if not obs.discovered_endpoints:
        return None
        
    for ep in obs.discovered_endpoints:
        hint = obs.endpoint_status_hints.get(ep, "").lower()
        if "critical" in hint or ("active" in hint and "simulated" not in hint):
            continue
            
        if obs.task_id == "task_2_orphan":
            if any(w in hint for w in ["simulated", "orphaned", "unused", "ignored", "benign", "safe", "deprecated"]):
                return ep
        elif obs.task_id == "task_3_stateful":
            if any(w in hint for w in ["simulated", "zombie", "stateful", "legacy", "mutation", "benign", "safe", "deprecated"]):
                return ep
    return None

def validate_task2_no_shadow_porting(obs, code: str, fallback_code: str) -> bool:
    """Heuristic validator for task_2_orphan.

    Reject candidates that appear to carry the orphaned dependency forward.
    This is intentionally compact and conservative.
    """
    if not code or "def migrate" not in code:
        return False

    try:
        compile(code, "<task2_candidate>", "exec")
    except Exception:
        return False

    lower_code = code.lower()
    legacy_str = obs.legacy_file_contents or ""

    # Known suspicious dependency-carrying tokens / APIs.
    suspicious_terms = [
        "requests",
        "urllib",
        "http",
        "https",
        "fetch(",
        "session.",
        "aiohttp",
        "socket",
        "api_call",
        "endpoint",
        "urlopen",
    ]

    # If the environment has identified a safe orphan target, do not let the code still reference it.
    safe_target = get_safe_decommission_target(obs)
    if safe_target and safe_target in code:
        return False

    # Reject obvious dead dependency/network carry-over.
    if any(term in lower_code for term in suspicious_terms):
        return False

    # If legacy had FETCH semantics but the endpoint result is ignored/orphaned,
    # the migrated Python should not preserve fetch-like scaffolding.
    if "FETCH " in legacy_str and ("inputs.get" not in code and "return" not in code):
        return False

    # If the deterministic fallback is already shadow-free but the candidate reintroduces networking,
    # reject the candidate.
    fallback_lower = (fallback_code or "").lower()
    if not any(term in fallback_lower for term in suspicious_terms) and any(term in lower_code for term in suspicious_terms):
        return False

    return True

def resolve_valid_code_for_task(obs, primary_code: str | None, fallback_code: str) -> str:
    """Validate ALL candidate code paths, not just LLM/repaired code.

    This helper ensures that:
    - if a primary candidate exists, it must pass task-specific validation
    - if it fails, fallback_code must ALSO pass task-specific validation
    - if fallback_code fails task-specific validation, fall back to a fresh deterministic draft
    """
    draft_code = generate_fallback_migration(obs.legacy_file_contents or "")

    candidate = primary_code if primary_code and "def migrate" in primary_code else fallback_code

    def passes_task_validation(code: str, fallback_for_validator: str) -> bool:
        if not code or "def migrate" not in code:
            return False

        # Always require syntax validity.
        try:
            compile(code, "<candidate>", "exec")
        except Exception:
            return False

        if obs.task_id == "task_1_pure":
            # For task_1, use the existing task_1 repair validator shape as a plausibility gate.
            return validate_task1_repair(obs.legacy_file_contents or "", draft_code, code)

        if obs.task_id == "task_2_orphan":
            return validate_task2_no_shadow_porting(obs, code, fallback_for_validator)

        if obs.task_id == "task_3_stateful":
            return validate_task3_mutation_signature(obs.legacy_file_contents or "", code)

        return True

    if passes_task_validation(candidate, fallback_code):
        return candidate

    if passes_task_validation(fallback_code, fallback_code):
        return fallback_code

    if passes_task_validation(draft_code, draft_code):
        return draft_code

    # Absolute last resort: still return deterministic draft rather than unchecked code.
    return draft_code

def should_enter_halt_state(obs, episode_state: dict) -> bool:
    """Bounded stopping rule after repair exhaustion.

    Uses EXECUTED action counters (maintained in run_inference_on_task),
    not model-proposed action counters.
    """
    has_repaired = episode_state.get("has_repaired", False)
    eq_attempts = episode_state.get("equivalence_attempts", 0)
    ping_attempts = episode_state.get("ping_attempts", 0)

    if obs.equivalence_status == "PASS":
        return False

    if obs.task_id == "task_1_pure":
        return has_repaired and eq_attempts > 2

    if obs.task_id == "task_2_orphan":
        return has_repaired and eq_attempts > 2

    if obs.task_id == "task_3_stateful":
        return has_repaired and (eq_attempts > 2 or ping_attempts > 2)

    return False


def get_halt_action(obs, episode_state: dict) -> ShadowCullAction:
    """Task-aware terminal/quarantine behavior using existing public actions only."""
    best_code = episode_state.get("best_code") or generate_fallback_migration(obs.legacy_file_contents)

    # No new public actions are allowed, so the safest available terminal action
    # is to submit the best available artifact and let the benchmark grade it.
    return ShadowCullAction(
        action_type=ActionType.SUBMIT_MIGRATION,
        target=obs.current_artifact_id,
        python_code=best_code
    )

def choose_next_action_with_guardrails(obs, action: ShadowCullAction, trajectory: list, llm_client: OpenAI, episode_state: dict) -> ShadowCullAction:
    action_type = action.action_type
    has_read = ActionType.READ_LEGACY_FILE.value in trajectory

    # Initialize phase-control state, but DO NOT increment counters here.
    episode_state.setdefault("equivalence_attempts", 0)
    episode_state.setdefault("ping_attempts", 0)
    episode_state.setdefault("halted", False)
    episode_state.setdefault("halt_reason", None)

    if not episode_state["halted"] and should_enter_halt_state(obs, episode_state):
        episode_state["halted"] = True
        episode_state["halt_reason"] = "repair_exhausted_nonpass"

    draft_code = generate_fallback_migration(obs.legacy_file_contents)
    
    current_best = episode_state.get("best_code") or draft_code

    # 1. TASK 1 PURE STRICT ROUTING
    if obs.task_id == "task_1_pure":
        if not obs.legacy_file_contents:
            return ShadowCullAction(
                action_type=ActionType.READ_LEGACY_FILE,
                target=obs.current_artifact_id
            )

        # Task 1 is always deterministic-draft-first.
        valid_code = episode_state.get("best_code") or draft_code

        # One repair pass only, and only after failed equivalence with a diff report.
        if (
            obs.equivalence_status != "PASS"
            and obs.equivalence_diff_report
            and not episode_state.get("has_repaired")
        ):
            repaired_code = repair_code_with_diff(llm_client, obs, valid_code)
            episode_state["has_repaired"] = True

            if repaired_code and validate_task1_repair(obs.legacy_file_contents, draft_code, repaired_code):
                valid_code = repaired_code
            else:
                valid_code = draft_code

            episode_state["best_code"] = valid_code
        elif episode_state.get("best_code"):
            valid_code = episode_state["best_code"]
        else:
            episode_state["best_code"] = valid_code

        if episode_state.get("halted"):
            return get_halt_action(obs, episode_state)

        if obs.equivalence_status != "PASS":
            return ShadowCullAction(
                action_type=ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code
            )
        else:
            return ShadowCullAction(
                action_type=ActionType.SUBMIT_MIGRATION,
                target=obs.current_artifact_id,
                python_code=valid_code
            )

    def get_valid_code(llm_code, fallback_code):
        return resolve_valid_code_for_task(obs, llm_code, fallback_code)

    valid_code = get_valid_code(action.python_code, current_best)
    
    # Repair pass
    if obs.equivalence_status != "PASS" and obs.equivalence_diff_report and not episode_state.get("has_repaired"):
        repaired_code = repair_code_with_diff(llm_client, obs, valid_code)
        episode_state["has_repaired"] = True
        valid_code = resolve_valid_code_for_task(obs, repaired_code, current_best)

    # Even if no repair happened, ensure the currently selected code path is task-valid.
    valid_code = resolve_valid_code_for_task(obs, valid_code, current_best)
    episode_state["best_code"] = valid_code

    safe_target = get_safe_decommission_target(obs)

    if episode_state.get("halted"):
        return get_halt_action(obs, episode_state)

    # --- ORIGINAL TASKS 2 AND 3 BEHAVIOR ---
    
    # 2. Force read first if not done
    if not has_read:
        return ShadowCullAction(action_type=ActionType.READ_LEGACY_FILE, target=obs.current_artifact_id)

    # 3. Prevent premature decommission or submit
    if action_type in (ActionType.DECOMMISSION_ENDPOINT, ActionType.SUBMIT_MIGRATION):
        if obs.equivalence_status != "PASS":
            return ShadowCullAction(action_type=ActionType.TEST_EQUIVALENCE, target=obs.current_artifact_id, python_code=valid_code)

    has_endpoints = bool(obs.discovered_endpoints and obs.endpoint_status_hints)

    if obs.task_id == "task_2_orphan":
        ping_count = trajectory.count(ActionType.PING_ENDPOINT.value)

        # Once we have enough endpoint evidence (or enough pings), stop wandering and test equivalence.
        if obs.equivalence_status == "PASS":
            if safe_target and ActionType.DECOMMISSION_ENDPOINT.value not in trajectory:
                return ShadowCullAction(
                    action_type=ActionType.DECOMMISSION_ENDPOINT,
                    target=safe_target
                )
            else:
                return ShadowCullAction(
                    action_type=ActionType.SUBMIT_MIGRATION,
                    target=obs.current_artifact_id,
                    python_code=valid_code
                )

        # If we already know enough about the orphan, go prove equivalence with the no-shadow code.
        if safe_target or has_endpoints or ping_count >= 2:
            return ShadowCullAction(
                action_type=ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code
            )

        # Do not allow pointless re-reading once the file is already present/read.
        if action_type == ActionType.READ_LEGACY_FILE and has_read:
            return ShadowCullAction(
                action_type=ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code
            )

        # Allow a bounded amount of probing, but do not let task_2 wander indefinitely.
        if action_type == ActionType.PING_ENDPOINT and ping_count >= 1:
            return ShadowCullAction(
                action_type=ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code
            )

        # Otherwise follow the model's suggested action if it's still in the early assessment phase.
        return action

    elif obs.task_id == "task_3_stateful":
        ping_count = trajectory.count(ActionType.PING_ENDPOINT.value)

        if not obs.legacy_file_contents:
            return ShadowCullAction(
                action_type=ActionType.READ_LEGACY_FILE,
                target=obs.current_artifact_id
            )

        # Mutation-first flow:
        # the current best validated code must prove equivalence before any destructive action.
        if obs.equivalence_status != "PASS":
            # Allow one bounded early assessment ping only if endpoint evidence is still absent.
            if action_type == ActionType.PING_ENDPOINT and not has_endpoints and ping_count < 1:
                return action

            return ShadowCullAction(
                action_type=ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code
            )

        # After PASS:
        # 1) If we have a safe target and have not yet decommissioned, do that first.
        if safe_target and ActionType.DECOMMISSION_ENDPOINT.value not in trajectory:
            return ShadowCullAction(
                action_type=ActionType.DECOMMISSION_ENDPOINT,
                target=safe_target
            )

        # 2) If equivalence passed but we still have no safe target:
        #    - allow one bounded final assessment ping only if endpoint evidence is still absent
        if not safe_target and not has_endpoints and ping_count < 2:
            return ShadowCullAction(
                action_type=ActionType.PING_ENDPOINT,
                target=obs.current_artifact_id
            )

        # 3) If equivalence passed, endpoint evidence exists, but still no safe target,
        #    enter halt/quarantine rather than auto-submitting as if the zombie were resolved.
        if not safe_target and has_endpoints:
            episode_state["halted"] = True
            episode_state["halt_reason"] = "task3_no_safe_target_after_pass"
            return get_halt_action(obs, episode_state)

        # 4) Otherwise submit only when either:
        #    - safe decommission has already been attempted, OR
        #    - bounded discovery is exhausted and no endpoint evidence exists
        return ShadowCullAction(
            action_type=ActionType.SUBMIT_MIGRATION,
            target=obs.current_artifact_id,
            python_code=valid_code
        )

    # 4. Repetition protection (catch-all)
    recent_actions = trajectory[-3:]
    if len(recent_actions) == 3 and all(a == action_type.value for a in recent_actions):
        return ShadowCullAction(action_type=ActionType.TEST_EQUIVALENCE, target=obs.current_artifact_id, python_code=valid_code)

    # 5. Ensure valid code if test or submit
    if action.action_type in (ActionType.TEST_EQUIVALENCE, ActionType.SUBMIT_MIGRATION):
        action.python_code = valid_code

    return action

def run_inference_on_task(task_id: str, env: ShadowCullEnv, llm_client: OpenAI):
    """Runs a single episode for the given task and returns the final score."""
    print(f"[START] {task_id}")
    
    # We rely on the environment's deterministic task cycling on reset()
    # to progress through easy -> medium -> hard tasks.
    result = env.reset()
    obs = result.observation
    done = result.done

    system_prompt = (
        "You are a highly risk-averse systems architect migrating legacy 'LegacyLang' to Python.\n"
        "Your goal is to replace the logic safely. You MUST NEVER port undocumented shadow dependencies,\n"
        "nor should you decommission them prematurely. Any mistake could trigger cascading failures.\n"
        "Priority order:\n"
        "1. `read_legacy_file` to understand the full logic and dependencies.\n"
        "2. `ping_endpoint` to probe endpoints to discover if they are orphaned, zombie, or active.\n"
        "3. `test_equivalence` to rigorously prove your Python code replicates output AND mutations.\n"
        "4. `decommission_endpoint` ONLY AFTER equivalence passes and you are certain it is safe.\n"
        "5. `submit_migration` to deploy the shim when all dependencies are cleanly resolved.\n\n"
        "Respond ONLY with a valid JSON object in this exact format, with no other text:\n"
        "{\n"
        '  "action_type": "one_of_the_5_actions",\n'
        '  "target": "optional_string",\n'
        '  "python_code": "optional_python_code_string"\n'
        "}"
    )

    trajectory = []
    step_count = 0
    episode_state = {
        "has_repaired": False,
        "best_code": None,
        "equivalence_attempts": 0,
        "ping_attempts": 0,
        "halted": False,
        "halt_reason": None,
    }
    
    while not done:
        step_count += 1
        # Build state context
        obs_dict = {
            "task_id": obs.task_id,
            "current_artifact_id": obs.current_artifact_id,
            "allowed_actions": obs.allowed_actions,
            "discovered_endpoints": obs.discovered_endpoints,
            "endpoint_status_hints": obs.endpoint_status_hints,
            "equivalence_status": obs.equivalence_status,
            "failure_modes": list(obs.failure_modes),
            "message": obs.message,
            "legacy_file_contents": obs.legacy_file_contents,
            "equivalence_diff_report": obs.equivalence_diff_report,
        }

        user_msg = f"Current Observation:\n{json.dumps(obs_dict, indent=2)}\n\nWhat is your next action JSON?"
        
        try:
            response = llm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                max_tokens=500,
                temperature=0.0
            )
            reply = response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM API Error: {e}")
            reply = ""

        action = parse_action(reply, obs.current_artifact_id)
        
        # Apply deterministic guardrails to avoid TIMEOUT loops
        action = choose_next_action_with_guardrails(obs, action, trajectory, llm_client, episode_state)
        
        # Count EXECUTED guarded actions, not raw model suggestions.
        if action.action_type == ActionType.TEST_EQUIVALENCE:
            episode_state["equivalence_attempts"] += 1
        elif action.action_type == ActionType.PING_ENDPOINT:
            episode_state["ping_attempts"] += 1

        trajectory.append(action.action_type.value)
        
        print(f"[STEP] {step_count} | Action: {action.action_type.value} | Equiv: {obs.equivalence_status} | Diff: {obs.equivalence_diff_report}")
        
        # Step environment
        result = env.step(action)
        obs = result.observation
        done = result.done

    match = re.search(r"\[Final Task Score:\s*([0-9.]+)\]", obs.message)
    if match:
        final_score = float(match.group(1))
    else:
        final_score = obs.metadata.get("final_task_score", 0.0) if obs.metadata else 0.0
    
    print(f"[END] {task_id} | Score: {final_score} | Failure Modes: {list(obs.failure_modes)}")
    
    return final_score

def main():
    llm_client = get_llm_client()
    
    # Normally the env is started separately
    env_url = ENV_URL
    
    try:
        # We run this in a loop to see if we can get through the task queue.
        with ShadowCullEnv(base_url=env_url).sync() as env:
            tasks = ["task_1_pure", "task_2_orphan", "task_3_stateful"]
            for task_id in tasks:
                run_inference_on_task(task_id, env, llm_client)
    except Exception as e:
        logger.error(f"Failed to connect to environment at {env_url}: {e}")

if __name__ == "__main__":
    main()
