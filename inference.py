import os
import sys
import json
import re
from openai import OpenAI
import logging

from client import ShadowCullEnv
from models import ShadowCullAction, ActionType

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Environment Variables
API_BASE_URL = os.getenv("API_BASE_URL", "https://api-inference.huggingface.co/v1/")
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/Llama-3-70b-chat-hf")
HF_TOKEN = os.getenv("HF_TOKEN", "")

def get_llm_client():
    if not HF_TOKEN:
        logger.warning("HF_TOKEN is not set. Inference might fail.")
    return OpenAI(
        base_url=API_BASE_URL,
        api_key=HF_TOKEN or "dummy"
    )

def parse_action(response_text: str) -> ShadowCullAction:
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
        # Safe fallback: just try to read the file again or ping a dummy to not crash
        return ShadowCullAction(
            action_type=ActionType.PING_ENDPOINT,
            target="http://fallback.safe"
        )

def run_inference_on_task(task_id: str, env: ShadowCullEnv, llm_client: OpenAI):
    """Runs a single episode for the given task and returns the final score."""
    logger.info(f"--- Starting Task: {task_id} ---")
    
    # Hack to reset to specific task (since our reset() doesn't take task_id directly)
    # OpenEnv normally controls the task distribution via standard reset.
    # In our environment.py, reset() currently defaults to task_3. We will just use
    # step actions or modify the environment to select tasks if needed. For now, the
    # environment server will need to randomly serve or cycle tasks, or we can just run it.
    
    # To properly implement this hackathon client, we'll connect and reset.
    result = env.reset()
    obs = result.observation
    done = result.done

    system_prompt = (
        "You are a cautious systems architect migrating legacy 'LegacyLang' to Python.\n"
        "Your goal is to replace the logic safely, but you MUST NEVER port undocumented shadow dependencies,\n"
        "nor should you decommission them prematurely.\n"
        "Priority order:\n"
        "1. `read_legacy_file` to see the logic.\n"
        "2. `ping_endpoint` to probe endpoints (orphaned, zombie, active).\n"
        "3. `test_equivalence` to prove your Python code replicates output AND mutations.\n"
        "4. `decommission_endpoint` ONLY AFTER equivalence passes.\n"
        "5. `submit_migration` to deploy the shim.\n\n"
        "Respond ONLY with a JSON object in this format:\n"
        "{\n"
        '  "action_type": "one_of_the_5_actions",\n'
        '  "target": "optional_string",\n'
        '  "python_code": "optional_python_code_string"\n'
        "}"
    )

    trajectory = []
    
    while not done:
        # Build state context
        obs_dict = {
            "task_id": obs.task_id,
            "current_artifact_id": obs.current_artifact_id,
            "allowed_actions": obs.allowed_actions,
            "discovered_endpoints": obs.discovered_endpoints,
            "endpoint_status_hints": obs.endpoint_status_hints,
            "equivalence_status": obs.equivalence_status,
            "failure_modes": obs.failure_modes,
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
            reply = '{"action_type": "ping_endpoint", "target": "http://fallback.safe"}'

        action = parse_action(reply)
        trajectory.append(action.action_type.value)
        
        logger.info(f"Agent chose: {action.action_type.value}")
        
        # Step environment
        result = env.step(action)
        obs = result.observation
        done = result.done

    final_score = obs.metadata.get("final_task_score", 0.0) if obs.metadata else 0.0
    logger.info(f"Task Finished. Trajectory: {trajectory}")
    logger.info(f"Final Score: {final_score}")
    
    return final_score

def main():
    llm_client = get_llm_client()
    
    # Normally the env is started separately
    env_url = os.getenv("ENV_URL", "http://localhost:8000")
    
    try:
        # We run this in a loop to see if we can get through the task queue.
        with ShadowCullEnv(base_url=env_url).sync() as env:
            scores = []
            for i in range(3):  # We know there are 3 tasks
                score = run_inference_on_task(f"Iteration_{i+1}", env, llm_client)
                scores.append(score)
            
            print("\\n=== Final Hackathon Results ===")
            for i, s in enumerate(scores):
                print(f"Run {i+1}: Final Score = {s}")
            print(f"Average Score: {sum(scores) / len(scores):.2f}")
    except Exception as e:
        logger.error(f"Failed to connect to environment at {env_url}: {e}")

if __name__ == "__main__":
    main()
