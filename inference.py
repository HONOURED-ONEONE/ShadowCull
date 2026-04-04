import os
import sys
import json
import re
from openai import OpenAI
import logging

from shadow_cull_env.client import ShadowCullEnv
from shadow_cull_env.models import ShadowCullAction, ActionType

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Environment Variables
API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/Llama-3-70b-chat-hf")
HF_TOKEN = os.getenv("HF_TOKEN")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")

def get_llm_client():
    if not HF_TOKEN:
        print("ERROR: HF_TOKEN environment variable is not set. Inference requires a valid token.")
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
            python_code=data.get("python_code")
        )
    except Exception as e:
        logger.error(f"Failed to parse action from LLM response: {e}")
        # Safe fallback policy: prefer reading artifacts over random probing. Never decommission.
        return ShadowCullAction(
            action_type=ActionType.READ_LEGACY_FILE,
            target=current_artifact_id
        )

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
        trajectory.append(action.action_type.value)
        
        print(f"[STEP] {step_count} | Action: {action.action_type.value}")
        
        # Step environment
        result = env.step(action)
        obs = result.observation
        done = result.done

    final_score = obs.metadata.get("final_task_score", 0.0) if obs.metadata else 0.0
    
    print(f"[END] {task_id} | Score: {final_score} | Failure Modes: {list(obs.failure_modes)}")
    
    return final_score

def main():
    print(f"Expected Execution Order: task_1_pure -> task_2_orphan -> task_3_stateful")
    print(f"Environment Variables Contract:")
    print(f"  API_BASE_URL: {API_BASE_URL}")
    print(f"  MODEL_NAME: {MODEL_NAME}")
    print(f"  HF_TOKEN: {'[SET]' if HF_TOKEN else '[NOT SET]'}")
    print(f"  ENV_URL: {ENV_URL}")
    print("\nLocal Run Command Example:")
    print("  uv run --project . server &")
    print("  export HF_TOKEN=your_token; python inference.py\n")

    llm_client = get_llm_client()
    
    # Normally the env is started separately
    env_url = ENV_URL
    
    try:
        # We run this in a loop to see if we can get through the task queue.
        with ShadowCullEnv(base_url=env_url).sync() as env:
            tasks = ["task_1_pure", "task_2_orphan", "task_3_stateful"]
            scores = []
            for task_id in tasks:
                score = run_inference_on_task(task_id, env, llm_client)
                scores.append(score)
            
            print("\n=== Final Hackathon Results ===")
            for task_id, s in zip(tasks, scores):
                print(f"Task {task_id}: Final Score = {s}")
            print(f"Average Score: {sum(scores) / len(scores):.2f}")
    except Exception as e:
        logger.error(f"Failed to connect to environment at {env_url}: {e}")

if __name__ == "__main__":
    main()
