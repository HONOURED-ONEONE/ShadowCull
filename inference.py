import os
import sys
import json
import re
import logging
from typing import Optional, Any, Dict, List, Tuple

from openai import OpenAI
from shadow_cull_env.client import ShadowCullEnv
from shadow_cull_env.models import ShadowCullAction, ActionType

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Structured stdout logging (must match official sample format)
# ------------------------------------------------------------------------------
TASK_BENCHMARK = os.getenv("SHADOWCULL_BENCHMARK", "shadowcull")

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)

def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )

def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}",
        flush=True,
    )

# ------------------------------------------------------------------------------
# Environment Variables
# ------------------------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/Llama-3-70b-chat-hf")
HF_TOKEN = os.getenv("HF_TOKEN")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")

# Optional local/offline switch
DISABLE_LLM = os.getenv("DISABLE_LLM", "0") == "1"

# Halt thresholds
MAX_EQ_ATTEMPTS_AFTER_REPAIR = 2
MAX_PING_ATTEMPTS_TASK3 = 2


# ------------------------------------------------------------------------------
# Client Setup
# ------------------------------------------------------------------------------
def get_llm_client() -> Optional[OpenAI]:
    if DISABLE_LLM:
        logger.warning("DISABLE_LLM=1 -> running without live model calls.")
        return None

    if not HF_TOKEN:
        sys.stderr.write(
            "ERROR: HF_TOKEN environment variable is not set. "
            "Set HF_TOKEN or use DISABLE_LLM=1.\n"
        )
        sys.exit(1)

    return OpenAI(
        base_url=API_BASE_URL,
        api_key=HF_TOKEN,
    )


# ------------------------------------------------------------------------------
# Transport / Parsing Hardening
# ------------------------------------------------------------------------------
def clean_python_code(code: Optional[str]) -> str:
    """Strip markdown fences / wrappers and normalize whitespace."""
    if not code:
        return ""

    code = code.strip()

    # Prefer fenced python block
    fenced = re.search(
        r"```(?:python)?\s*(.*?)\s*```",
        code,
        re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        return fenced.group(1).strip()

    # Remove stray wrappers if malformed
    code = re.sub(r"^```(?:python|json)?", "", code, flags=re.IGNORECASE).strip()
    code = re.sub(r"```$", "", code, flags=re.IGNORECASE).strip()
    return code

def _single_line(s: str, limit: int = 240) -> str:
    """Collapse multiline strings into a grep-friendly single line."""
    if not s:
        return ""
    s = " | ".join(part.strip() for part in s.splitlines() if part.strip())
    return s[:limit]


def extract_fenced_code(text: str) -> str:
    """Extract first fenced python block if present."""
    if not text:
        return ""
    m = re.search(
        r"```(?:python)?\s*(.*?)\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return clean_python_code(m.group(1)) if m else ""


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Robust JSON extraction:
    1) fenced ```json block
    2) direct whole-string JSON
    3) first balanced {...} object that parses
    """
    if not text:
        return None

    # 1) fenced json
    fenced = re.search(
        r"```json\s*(\{.*?\})\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass

    # 2) direct whole-string JSON
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except Exception:
            pass

    # 3) first balanced object
    starts = [m.start() for m in re.finditer(r"\{", text)]
    for s in starts:
        depth = 0
        for i in range(s, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[s : i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break

    return None


def regex_extract_action_fields(text: str) -> Dict[str, Any]:
    """
    Last-resort field extraction if JSON is malformed.
    """
    data: Dict[str, Any] = {}

    m_action = re.search(
        r'"?action_type"?\s*[:=]\s*"?(read_legacy_file|ping_endpoint|test_equivalence|decommission_endpoint|submit_migration)"?',
        text,
        re.IGNORECASE,
    )
    if m_action:
        data["action_type"] = m_action.group(1)

    m_target = re.search(r'"?target"?\s*[:=]\s*"([^"]+)"', text)
    if m_target:
        data["target"] = m_target.group(1)

    # Legacy compatibility: inline python_code in malformed JSON-ish output
    m_code = re.search(r'"?python_code"?\s*[:=]\s*"(.*)"', text, re.DOTALL)
    if m_code:
        data["python_code"] = m_code.group(1)

    return data


def safe_action_type(raw: Any) -> ActionType:
    if isinstance(raw, ActionType):
        return raw

    if not raw:
        return ActionType.READ_LEGACY_FILE

    try:
        return ActionType(raw)
    except Exception:
        pass

    if isinstance(raw, str):
        normalized = raw.strip().lower()
        mapping = {
            "read_legacy_file": ActionType.READ_LEGACY_FILE,
            "ping_endpoint": ActionType.PING_ENDPOINT,
            "test_equivalence": ActionType.TEST_EQUIVALENCE,
            "decommission_endpoint": ActionType.DECOMMISSION_ENDPOINT,
            "submit_migration": ActionType.SUBMIT_MIGRATION,
        }
        return mapping.get(normalized, ActionType.READ_LEGACY_FILE)

    return ActionType.READ_LEGACY_FILE


def parse_action(response_text: str, current_artifact_id: str) -> ShadowCullAction:
    """
    Hardened parser:
    - accepts JSON action + separate fenced python block
    - accepts legacy inline python_code
    - recovers from malformed JSON where possible
    - can salvage a fenced code block even when JSON is broken
    """
    try:
        data = extract_json_object(response_text)
        parser_path = "json"

        if data is None:
            data = regex_extract_action_fields(response_text)
            parser_path = "regex-fallback"

        code = extract_fenced_code(response_text)

        if not data:
            # If JSON is unrecoverable but we do have code, salvage it.
            if code:
                logger.info("parse_action path=code-salvage action=test_equivalence code=yes")
                return ShadowCullAction(
                    action_type=ActionType.TEST_EQUIVALENCE,
                    target=current_artifact_id,
                    python_code=code,
                )
            raise ValueError("No action payload found")

        action_type = safe_action_type(data.get("action_type"))
        target = data.get("target") or current_artifact_id

        # Fallback to inline python_code if separate fenced code was not found
        if not code and data.get("python_code"):
            code = clean_python_code(data.get("python_code"))

        logger.info(
            f"parse_action path={parser_path} action={action_type.value} code={'yes' if code else 'no'}"
        )

        return ShadowCullAction(
            action_type=action_type,
            target=target,
            python_code=code or None,
        )

    except Exception as e:
        logger.error(f"Failed to parse action from LLM response: {e}")
        return ShadowCullAction(
            action_type=ActionType.READ_LEGACY_FILE,
            target=current_artifact_id,
        )


# ------------------------------------------------------------------------------
# Allowed-action helpers
# ------------------------------------------------------------------------------
def normalize_allowed_actions(obs) -> set:
    raw = getattr(obs, "allowed_actions", None) or []
    out = set()
    for item in raw:
        if isinstance(item, ActionType):
            out.add(item.value)
        else:
            out.add(str(item))
    return out


def is_allowed(obs, action_type: ActionType) -> bool:
    allowed = normalize_allowed_actions(obs)
    if not allowed:
        return True
    return action_type.value in allowed


def safe_make_action(
    obs,
    action_type: ActionType,
    target: Optional[str] = None,
    python_code: Optional[str] = None,
) -> ShadowCullAction:
    """
    Make an action, but coerce it into an allowed conservative fallback if needed.
    """
    if is_allowed(obs, action_type):
        return ShadowCullAction(
            action_type=action_type,
            target=target or getattr(obs, "current_artifact_id", None),
            python_code=python_code,
        )

    # Conservative fallback ordering
    if is_allowed(obs, ActionType.READ_LEGACY_FILE):
        return ShadowCullAction(
            action_type=ActionType.READ_LEGACY_FILE,
            target=getattr(obs, "current_artifact_id", None),
        )

    if python_code and is_allowed(obs, ActionType.TEST_EQUIVALENCE):
        return ShadowCullAction(
            action_type=ActionType.TEST_EQUIVALENCE,
            target=getattr(obs, "current_artifact_id", None),
            python_code=python_code,
        )

    if python_code and is_allowed(obs, ActionType.SUBMIT_MIGRATION):
        return ShadowCullAction(
            action_type=ActionType.SUBMIT_MIGRATION,
            target=getattr(obs, "current_artifact_id", None),
            python_code=python_code,
        )

    if is_allowed(obs, ActionType.PING_ENDPOINT):
        return ShadowCullAction(
            action_type=ActionType.PING_ENDPOINT,
            target=getattr(obs, "current_artifact_id", None),
        )

    # Last resort
    return ShadowCullAction(
        action_type=action_type,
        target=target or getattr(obs, "current_artifact_id", None),
        python_code=python_code,
    )


# ------------------------------------------------------------------------------
# Deterministic Fallback Translation
# ------------------------------------------------------------------------------
def generate_fallback_migration(legacy_content: Optional[str]) -> str:
    """
    Canonical ugly-but-faithful deterministic transpilation for simple LegacyLang.
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
        return len(token) >= 2 and (
            (token.startswith('"') and token.endswith('"')) or
            (token.startswith("'") and token.endswith("'"))
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

        # Do not port FETCH into Python
        if line.startswith("FETCH "):
            continue

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

            # Parse RHS before registering LHS
            m = re.match(r"^(\S+)\s*([\+\-\*/])\s*(\S+)$", right)
            if m:
                a, op, b = m.groups()
                rhs = f"{parse_operand(a)} {op} {parse_operand(b)}"
            else:
                rhs = parse_operand(right)

            python_lines.append(f"    {left} = {rhs}")
            assigned_vars.add(left)
            last_assigned_var = left

    if not has_return:
        python_lines.append(f"    return {last_assigned_var}" if last_assigned_var else "    return 0")

    body = [ln for ln in python_lines[1:] if ln.strip()]
    if len(body) == 1 and body[0].strip() == "return 0":
        return "def migrate(inputs, network):\n    return 0"

    return "\n".join(python_lines)


# ------------------------------------------------------------------------------
# Repair Path
# ------------------------------------------------------------------------------
def repair_code_with_diff(
    llm_client: Optional[OpenAI],
    obs,
    current_draft: str,
) -> Optional[str]:
    """
    One-pass repair using equivalence diff.
    Safe no-op if LLM unavailable.
    """
    if llm_client is None:
        return None

    prompt = (
        "You are repairing a Python migration script.\n\n"
        "OUTPUT CONTRACT:\n"
        "Return ONLY a fenced ```python``` block containing the repaired code.\n"
        "Do NOT put the code inside JSON.\n\n"
        "Original LegacyLang code:\n"
        f"{obs.legacy_file_contents}\n\n"
        "Current Python draft:\n"
        f"```python\n{current_draft}\n```\n\n"
        "Equivalence diff report:\n"
        f"{obs.equivalence_diff_report}\n\n"
        "Requirements:\n"
        "- The code MUST start with: def migrate(inputs, network):\n"
        "- Preserve semantics exactly\n"
    )

    try:
        response = llm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            temperature=0.0,
        )
        reply = response.choices[0].message.content or ""
        code = extract_fenced_code(reply) or clean_python_code(reply)

        if not code or "def migrate" not in code:
            return None

        if (
            obs.task_id == "task_3_stateful"
            and obs.legacy_file_contents
            and "MUTATE_STATE" in obs.legacy_file_contents
            and "mutate_state" not in code
        ):
            return None

        return code

    except Exception as e:
        logger.error(f"Repair failed: {e}")
        return None


# ------------------------------------------------------------------------------
# Validators
# ------------------------------------------------------------------------------
def extract_task3_mutation_signature(legacy_content: Optional[str]) -> List[Tuple[str, str]]:
    if not legacy_content:
        return []

    signature: List[Tuple[str, str]] = []
    for raw_line in legacy_content.split("\n"):
        line = raw_line.strip()
        if not line.startswith("MUTATE_STATE "):
            continue
        parts = line.split()
        if len(parts) >= 3:
            signature.append((parts[1].strip(), parts[2].strip()))
    return signature


def validate_task3_mutation_signature(legacy_content: Optional[str], code: str) -> bool:
    """
    Structural validator for Task 3.
    Behavioral equivalence belongs to the environment.
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

    if "mutate_state" not in code.lower():
        return False

    code_lines = [
        line for line in code.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(code_lines) <= 2:
        return False

    for key, value in signature:
        if key not in code:
            return False

        if re.match(r"^-?\d+(?:\.\d+)?$", value) and value not in code:
            return False

        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"')) or
            (value.startswith("'") and value.endswith("'"))
        ):
            if value not in code:
                return False

    return True


def validate_task1_repair(legacy_content: Optional[str], draft_code: str, repaired_code: str) -> bool:
    if not repaired_code or "def migrate" not in repaired_code:
        return False

    try:
        compile(repaired_code, "<task1_repair>", "exec")
    except Exception:
        return False

    legacy_str = legacy_content or ""
    has_logic = any(sym in legacy_str for sym in ["=", "+", "-", "*", "/"])

    returns_constant = re.search(
        r"""return\s+(0|None|\[\]|\{\}|''|""|False|True|-?\d+(?:\.\d+)?)\s*$""",
        repaired_code.strip(),
        re.MULTILINE,
    )
    if has_logic and returns_constant:
        return False

    if "inputs.get" in draft_code and "inputs" not in repaired_code:
        return False

    code_lines = [
        line for line in repaired_code.split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]
    if has_logic and len(code_lines) <= 2:
        return False

    return True


def get_safe_decommission_target(obs) -> Optional[str]:
    """
    Conservative broadened hint parsing.
    Never default-safe blindly.
    """
    if not obs.discovered_endpoints:
        return None

    for ep in obs.discovered_endpoints:
        hint = (obs.endpoint_status_hints.get(ep, "") or "").lower()

        if "critical" in hint or ("active" in hint and "simulated" not in hint):
            continue

        if obs.task_id == "task_2_orphan":
            if any(
                w in hint for w in [
                    "simulated", "orphaned", "unused", "ignored",
                    "benign", "safe", "deprecated"
                ]
            ):
                return ep

        elif obs.task_id == "task_3_stateful":
            if any(
                w in hint for w in [
                    "simulated", "zombie", "stateful", "legacy",
                    "mutation", "benign", "safe", "deprecated"
                ]
            ):
                return ep

    return None


def validate_task2_no_shadow_porting(obs, code: str, fallback_code: str) -> bool:
    """
    Validate Task 2 (orphaned dependency) candidates.
    Reject shadow-porting, malformed, or semantically invalid migrations.
    """

    # ------------------------------------------------------------------
    # HARD GUARDRAILS — malformed / contaminated payloads must never pass
    # ------------------------------------------------------------------

    if not code:
        return False

    stripped = code.strip()
    if not stripped:
        return False

    # Task 2 MUST define exactly migrate(inputs, network)
    if "def migrate(inputs, network):" not in stripped:
        return False

    # Must be syntactically valid Python
    try:
        compile(stripped, "<task2_candidate>", "exec")
    except Exception:
        return False

    lower_code = stripped.lower()
    legacy_str = obs.legacy_file_contents or ""

    # Explicitly reject known contaminated helper payloads
    forbidden_helpers = [
        "legacy_orphan",
        "python_orphan",
    ]
    for bad in forbidden_helpers:
        if bad in lower_code:
            return False

    # Reject any network / HTTP / endpoint residue
    forbidden_terms = [
        "http",
        "https",
        "requests",
        "urllib",
        "aiohttp",
        "socket",
        "endpoint",
        "urlopen",
        "fetch(",
        "session.",
    ]
    for term in forbidden_terms:
        if term in lower_code:
            return False

    # ------------------------------------------------------------------
    # Semantic guardrail — trivial constant returns are invalid when
    # legacy logic clearly contains computation
    # ------------------------------------------------------------------

    has_legacy_logic = any(sym in legacy_str for sym in ["=", "+", "-", "*", "/"])
    returns_constant = re.search(
        r"return\s+(0|None|\[\]|\{\}|''|\"\"|False|True|-?\d+(?:\.\d+)?)\s*$",
        stripped,
        re.MULTILINE,
    )
    if has_legacy_logic and returns_constant:
        return False

    # ------------------------------------------------------------------
    # Shadow-porting guardrails (existing logic preserved)
    # ------------------------------------------------------------------

    safe_target = get_safe_decommission_target(obs)
    if safe_target and safe_target in stripped:
        return False

    if "FETCH " in legacy_str and ("inputs.get" not in code and "return" not in code):
        return False

    if not any(term in (fallback_code or "").lower() for term in forbidden_terms) and \
       any(term in lower_code for term in forbidden_terms):
        return False

    return True


# ------------------------------------------------------------------------------
# Candidate Resolution
# ------------------------------------------------------------------------------
def resolve_valid_code_for_task(
    obs,
    primary_code: Optional[str],
    fallback_code: str,
) -> str:
    """
    Validate ALL candidate paths:
    primary -> fallback -> fresh deterministic draft
    """
    draft_code = generate_fallback_migration(obs.legacy_file_contents or "")
    candidate = primary_code if primary_code and "def migrate" in primary_code else fallback_code

    def passes(code: str, validator_fallback: str) -> bool:
        if not code or "def migrate" not in code:
            return False

        try:
            compile(code, "<candidate>", "exec")
        except Exception:
            return False

        if obs.task_id == "task_1_pure":
            return validate_task1_repair(obs.legacy_file_contents or "", draft_code, code)

        if obs.task_id == "task_2_orphan":
            return validate_task2_no_shadow_porting(obs, code, validator_fallback)

        if obs.task_id == "task_3_stateful":
            return validate_task3_mutation_signature(obs.legacy_file_contents or "", code)

        return True

    for code in [candidate, fallback_code, draft_code]:
        if passes(code, fallback_code):
            return code

    return draft_code


# ------------------------------------------------------------------------------
# Halt / Fail Logic
# ------------------------------------------------------------------------------
def should_enter_halt_state(obs, episode_state: dict) -> bool:
    has_repaired = episode_state.get("has_repaired", False)
    eq_attempts = episode_state.get("equivalence_attempts", 0)
    ping_attempts = episode_state.get("ping_attempts", 0)

    if obs.equivalence_status == "PASS":
        return False

    if obs.task_id == "task_1_pure":
        return has_repaired and eq_attempts > MAX_EQ_ATTEMPTS_AFTER_REPAIR

    if obs.task_id == "task_2_orphan":
        return has_repaired and eq_attempts > MAX_EQ_ATTEMPTS_AFTER_REPAIR

    if obs.task_id == "task_3_stateful":
        return has_repaired and (
            eq_attempts > MAX_EQ_ATTEMPTS_AFTER_REPAIR
            or ping_attempts > MAX_PING_ATTEMPTS_TASK3
        )

    return False


def get_halt_action(obs, episode_state: dict) -> ShadowCullAction:
    best_code = episode_state.get("best_code") or generate_fallback_migration(obs.legacy_file_contents)
    return ShadowCullAction(
        action_type=ActionType.SUBMIT_MIGRATION,
        target=obs.current_artifact_id,
        python_code=best_code,
    )


# ------------------------------------------------------------------------------
# Guardrails / Policy
# ------------------------------------------------------------------------------
def choose_next_action_with_guardrails(
    obs,
    action: ShadowCullAction,
    trajectory: List[str],
    llm_client: Optional[OpenAI],
    episode_state: dict,
) -> ShadowCullAction:

    action_type = action.action_type
    has_read = ActionType.READ_LEGACY_FILE.value in trajectory

    episode_state.setdefault("equivalence_attempts", 0)
    episode_state.setdefault("ping_attempts", 0)
    episode_state.setdefault("halted", False)
    episode_state.setdefault("halt_reason", None)
    episode_state.setdefault("best_code_source", None)

    if not episode_state["halted"] and should_enter_halt_state(obs, episode_state):
        episode_state["halted"] = True
        episode_state["halt_reason"] = "repair_exhausted_nonpass"

    draft_code = generate_fallback_migration(obs.legacy_file_contents)
    current_best = episode_state.get("best_code") or draft_code

    # NEW: do not preserve an empty pre-read fallback forever for dependency tasks.
    trivial_empty_fallback = "def migrate(inputs, network):\n    return 0"
    if obs.task_id in ("task_2_orphan", "task_3_stateful"):
        if not obs.legacy_file_contents:
            # Force read first and avoid locking in a meaningless best_code.
            episode_state["best_code"] = None
            episode_state["best_code_source"] = None
            return safe_make_action(
                obs,
                ActionType.READ_LEGACY_FILE,
                target=obs.current_artifact_id,
            )
        elif episode_state.get("best_code") == trivial_empty_fallback:
            # Replace the stale pre-read fallback with a fresh deterministic draft
            # built from the now-available legacy contents.
            current_best = draft_code
            episode_state["best_code"] = draft_code
            episode_state["best_code_source"] = "draft"

    # --------------------------------------------------------------------------
    # TASK 1 — deterministic draft first, repair second
    # --------------------------------------------------------------------------
    if obs.task_id == "task_1_pure":
        if not obs.legacy_file_contents:
            return safe_make_action(
                obs,
                ActionType.READ_LEGACY_FILE,
                target=obs.current_artifact_id,
            )

        valid_code = episode_state.get("best_code") or draft_code
        if episode_state.get("best_code") is None:
            episode_state["best_code_source"] = "draft"

        if (
            obs.equivalence_status != "PASS"
            and obs.equivalence_diff_report
            and not episode_state.get("has_repaired")
        ):
            repaired_code = repair_code_with_diff(llm_client, obs, valid_code)
            episode_state["has_repaired"] = True

            if repaired_code and validate_task1_repair(
                obs.legacy_file_contents, draft_code, repaired_code
            ):
                valid_code = repaired_code
                episode_state["best_code_source"] = "repair"
            else:
                valid_code = draft_code
                episode_state["best_code_source"] = "draft"

            episode_state["best_code"] = valid_code

        elif episode_state.get("best_code"):
            valid_code = episode_state["best_code"]

        else:
            episode_state["best_code"] = valid_code
            episode_state["best_code_source"] = "draft"

        if episode_state.get("halted"):
            return get_halt_action(obs, episode_state)

        if obs.equivalence_status != "PASS":
            return safe_make_action(
                obs,
                ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code,
            )

        return safe_make_action(
            obs,
            ActionType.SUBMIT_MIGRATION,
            target=obs.current_artifact_id,
            python_code=valid_code,
        )

    # --------------------------------------------------------------------------
    # TASKS 2 / 3 — all candidate paths validated
    # --------------------------------------------------------------------------
    valid_code = resolve_valid_code_for_task(obs, action.python_code, current_best)

    if valid_code == action.python_code and action.python_code:
        episode_state["best_code_source"] = "llm"
    elif valid_code == current_best:
        episode_state["best_code_source"] = episode_state.get("best_code_source") or "current_best"
    else:
        episode_state["best_code_source"] = "draft"

    if (
        obs.equivalence_status != "PASS"
        and obs.equivalence_diff_report
        and not episode_state.get("has_repaired")
    ):
        repaired_code = repair_code_with_diff(llm_client, obs, valid_code)
        episode_state["has_repaired"] = True
        resolved = resolve_valid_code_for_task(obs, repaired_code, current_best)
        if repaired_code and resolved == repaired_code:
            episode_state["best_code_source"] = "repair"
        valid_code = resolved

    valid_code = resolve_valid_code_for_task(obs, valid_code, current_best)
    episode_state["best_code"] = valid_code

    safe_target = get_safe_decommission_target(obs)
    has_endpoints = bool(obs.discovered_endpoints and obs.endpoint_status_hints)

    if episode_state.get("halted"):
        return get_halt_action(obs, episode_state)

    # Always read file first if not done
    if not has_read:
        return safe_make_action(
            obs,
            ActionType.READ_LEGACY_FILE,
            target=obs.current_artifact_id,
        )

    # Never allow premature decommission/submit before equivalence PASS
    if action_type in (ActionType.DECOMMISSION_ENDPOINT, ActionType.SUBMIT_MIGRATION):
        if obs.equivalence_status != "PASS":
            return safe_make_action(
                obs,
                ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code,
            )

    # --------------------------------------------------------------------------
    # TASK 2 — orphan handling
    # --------------------------------------------------------------------------
    if obs.task_id == "task_2_orphan":
        ping_count = trajectory.count(ActionType.PING_ENDPOINT.value)

        if obs.equivalence_status == "PASS":
            if safe_target and ActionType.DECOMMISSION_ENDPOINT.value not in trajectory:
                return safe_make_action(
                    obs,
                    ActionType.DECOMMISSION_ENDPOINT,
                    target=safe_target,
                )
            return safe_make_action(
                obs,
                ActionType.SUBMIT_MIGRATION,
                target=obs.current_artifact_id,
                python_code=valid_code,
            )

        if safe_target or has_endpoints or ping_count >= 2:
            return safe_make_action(
                obs,
                ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code,
            )

        if action_type == ActionType.READ_LEGACY_FILE and has_read:
            return safe_make_action(
                obs,
                ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code,
            )

        if action_type == ActionType.PING_ENDPOINT and ping_count >= 1:
            return safe_make_action(
                obs,
                ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code,
            )

        # FINAL TASK-2 GUARDRAIL:
        # Never allow the original malformed action.python_code to leak into
        # TEST_EQUIVALENCE or SUBMIT_MIGRATION once valid_code has been resolved.
        return safe_make_action(
            obs,
            action.action_type,
            target=action.target or obs.current_artifact_id,
            python_code=valid_code
            if action.action_type in (ActionType.TEST_EQUIVALENCE, ActionType.SUBMIT_MIGRATION)
            else action.python_code,
        )

    # --------------------------------------------------------------------------
    # TASK 3 — mutation-first zombie handling
    # --------------------------------------------------------------------------
    if obs.task_id == "task_3_stateful":
        ping_count = trajectory.count(ActionType.PING_ENDPOINT.value)

        if not obs.legacy_file_contents:
            return safe_make_action(
                obs,
                ActionType.READ_LEGACY_FILE,
                target=obs.current_artifact_id,
            )

        if obs.equivalence_status != "PASS":
            if action_type == ActionType.PING_ENDPOINT and not has_endpoints and ping_count < 1:
                return safe_make_action(
                    obs,
                    ActionType.PING_ENDPOINT,
                    target=obs.current_artifact_id,
                )

            return safe_make_action(
                obs,
                ActionType.TEST_EQUIVALENCE,
                target=obs.current_artifact_id,
                python_code=valid_code,
            )

        # PASS path
        if safe_target and ActionType.DECOMMISSION_ENDPOINT.value not in trajectory:
            return safe_make_action(
                obs,
                ActionType.DECOMMISSION_ENDPOINT,
                target=safe_target,
            )

        if not safe_target and not has_endpoints and ping_count < 2:
            return safe_make_action(
                obs,
                ActionType.PING_ENDPOINT,
                target=obs.current_artifact_id,
            )

        if not safe_target and has_endpoints:
            episode_state["halted"] = True
            episode_state["halt_reason"] = "task3_no_safe_target_after_pass"
            return get_halt_action(obs, episode_state)

        return safe_make_action(
            obs,
            ActionType.SUBMIT_MIGRATION,
            target=obs.current_artifact_id,
            python_code=valid_code,
        )

    # Catch-all fallback
    return safe_make_action(
        obs,
        action.action_type,
        target=action.target or obs.current_artifact_id,
        python_code=valid_code if action.action_type in (ActionType.TEST_EQUIVALENCE, ActionType.SUBMIT_MIGRATION) else action.python_code,
    )


# ------------------------------------------------------------------------------
# Execution Loop
# ------------------------------------------------------------------------------
def run_inference_on_task(task_id: str, env: ShadowCullEnv, llm_client: Optional[OpenAI]):
    log_start(task=task_id, env=TASK_BENCHMARK, model=MODEL_NAME)

    result = env.reset()
    obs = result.observation
    done = result.done

    rewards: List[float] = []
    final_score = 0.0
    success = False

    system_prompt = (
        "You are a highly risk-averse systems architect migrating LegacyLang to Python.\n\n"
        "IMPORTANT OUTPUT CONTRACT:\n"
        "1) Output a JSON object describing ONLY the action:\n"
        '{"action_type":"...", "target":"optional_string"}\n'
        "2) If code is needed, output it in a separate fenced ```python``` block AFTER the JSON.\n"
        "3) Do NOT put multiline Python inside a JSON string.\n\n"
        "Action principles:\n"
        "- read_legacy_file before code reasoning\n"
        "- test_equivalence before destructive actions\n"
        "- decommission_endpoint only after PASS and safe evidence\n"
        "- submit_migration only when the dependency path is resolved or safely halted\n"
    )

    trajectory: List[str] = []
    step_count = 0
    episode_state = {
        "last_action_error": None,
        "has_repaired": False,
        "best_code": None,
        "best_code_source": None,
        "equivalence_attempts": 0,
        "ping_attempts": 0,
        "halted": False,
        "halt_reason": None,
    }

    try:
        while not done:
            step_count += 1

            obs_dict = {
                "task_id": obs.task_id,
                "current_artifact_id": obs.current_artifact_id,
                "allowed_actions": getattr(obs, "allowed_actions", None),
                "discovered_endpoints": getattr(obs, "discovered_endpoints", None),
                "endpoint_status_hints": getattr(obs, "endpoint_status_hints", None),
                "equivalence_status": getattr(obs, "equivalence_status", None),
                "failure_modes": list(getattr(obs, "failure_modes", [])),
                "message": getattr(obs, "message", None),
                "legacy_file_contents": getattr(obs, "legacy_file_contents", None),
                "equivalence_diff_report": getattr(obs, "equivalence_diff_report", None),
            }

            if llm_client is None:
                reply = ""
            else:
                try:
                    response = llm_client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": f"Current Observation:\n{json.dumps(obs_dict, indent=2)}",
                            },
                        ],
                        max_tokens=700,
                        temperature=0.0,
                    )
                    reply = response.choices[0].message.content or ""
                except Exception as e:
                    logger.error(f"LLM API Error: {e}")
                    reply = ""

            action = parse_action(reply, obs.current_artifact_id)

            action = choose_next_action_with_guardrails(
                obs,
                action,
                trajectory,
                llm_client,
                episode_state,
            )

            # Count EXECUTED guarded actions
            if action.action_type == ActionType.TEST_EQUIVALENCE:
                episode_state["equivalence_attempts"] += 1
            elif action.action_type == ActionType.PING_ENDPOINT:
                episode_state["ping_attempts"] += 1

            # Task-2 raw payload debugging to STDERR only.
            # This is intentionally NOT printed to stdout so that validator parsing
            # of [START]/[STEP]/[END] is not disturbed.
            if (
                obs.task_id == "task_2_orphan"
                and action.action_type in (ActionType.TEST_EQUIVALENCE, ActionType.SUBMIT_MIGRATION)
            ):
                code = action.python_code or ""
                sys.stderr.write(
                    "[TASK2_RAW] "
                    f"Action={action.action_type.value} | "
                    f"Len={len(code)} | "
                    f"StartsWithDef={code.lstrip().startswith('def migrate')} | "
                    f"ContainsFETCH={'FETCH ' in code} | "
                    f"ContainsHTTP={('http' in code.lower())} | "
                    f"Repr={repr(code[:500])}\n"
                )
                sys.stderr.flush()

            trajectory.append(action.action_type.value)

            result = env.step(action)
            obs = result.observation
            done = result.done

            reward = float(getattr(result, "reward", 0.0) or 0.0)
            rewards.append(reward)
            last_error = getattr(obs, "last_action_error", None)
            episode_state["last_action_error"] = last_error
            action_str = action.action_type.value

            log_step(
                step=step_count,
                action=action_str,
                reward=reward,
                done=done,
                error=last_error,
            )

            # Task-2 equivalence diff debugging to STDERR only.
            if obs.task_id == "task_2_orphan":
                if obs.equivalence_status == "FAIL" and obs.equivalence_diff_report:
                    code_preview = _single_line((episode_state.get("best_code") or "")[:400], limit=240)
                    diff_preview = _single_line(obs.equivalence_diff_report, limit=320)
                    sys.stderr.write(
                        f"[TASK2_DIFF] Step: {step_count} | "
                        f"BestSource: {episode_state.get('best_code_source')} | "
                        f"Diff: {diff_preview} | "
                        f"CodePreview: {code_preview}\n"
                    )
                    sys.stderr.flush()

        message = getattr(obs, "message", "") or ""
        match = re.search(r"\[Final Task Score:\s*([0-9.]+)\]", message)
        if match:
            try:
                final_score = float(match.group(1))
            except Exception:
                final_score = 0.0

        if not final_score:
            final_score = obs.metadata.get("final_task_score", 0.0) if getattr(obs, "metadata", None) else 0.0

        failure_modes = list(getattr(obs, "failure_modes", []))
        success = bool(final_score > 0.0 and not failure_modes)

    finally:
        log_end(
            success=success,
            steps=step_count,
            score=final_score,
            rewards=rewards,
        )

    return final_score


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
def main():
    llm_client = get_llm_client()

    try:
        with ShadowCullEnv(base_url=ENV_URL).sync() as env:
            for task_id in ["task_1_pure", "task_2_orphan", "task_3_stateful"]:
                run_inference_on_task(task_id, env, llm_client)
    except Exception as e:
        logger.error(f"Failed to connect to environment at {ENV_URL}: {e}")


if __name__ == "__main__":
    main()