# Final Submission Checklist

- [x] **Required Files Present**: Core engine, tasks, grader, client, `README.md`, `openenv.yaml`.
- [x] **inference.py at Root**: Successfully hardened, risk-averse system prompt, handles missing `HF_TOKEN`, defaults to HF router, and located at repository root.
- [x] **3 Canonical Tasks Verified**: `task_1_pure`, `task_2_orphan`, `task_3_stateful` are explicitly evaluated in order without mechanics changes.
- [x] **Grading Normalized**: Scores strictly calculated on `[0.0, 1.0]` scale.
- [x] **Validation**: `openenv validate .` completes with `[OK]`.

### Final Deploy Commands

**1. Validate the environment**
```bash
openenv validate .
```

**2. Build the Docker image**
```bash
openenv build .
```

**3. Push to Hugging Face**
```bash
openenv push <your_hf_username>/shadow_cull_env
```

### Required Environment Variables (for `inference.py`)
- `API_BASE_URL` (Defaults to `https://router.huggingface.co/v1`)
- `MODEL_NAME` (Defaults to `meta-llama/Llama-3-70b-chat-hf`)
- `HF_TOKEN` (Must be set for real inference)
- `ENV_URL` (Defaults to `http://localhost:8000`)
