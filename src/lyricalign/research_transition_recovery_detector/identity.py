from __future__ import annotations
from dataclasses import asdict
import hashlib, json
from .contracts import TransitionState, WindowRequest

def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

def state_hash(state: TransitionState) -> str:
    return _canonical_hash(asdict(state))

def forward_cache_key(request: WindowRequest, *, config_hash: str, model_identity: dict, env_identity: str, hidden_schema: str | None = None) -> str:
    # 把 request 全字段（含 parent_state_hash/query_estimator_version/window_index）
    # + config_hash + model_identity + env_identity + hidden_schema 全部并入 canonical hash
    payload = {"request": asdict(request), "config_hash": config_hash, "model": model_identity, "env": env_identity, "hidden_schema": hidden_schema}
    return _canonical_hash(payload)

def trajectory_cache_key(state_hash_value: str, policy_identity: str, forward_key: str) -> str:
    return _canonical_hash({"parent_state": state_hash_value, "policy": policy_identity, "forward": forward_key})

def request_id_for(state: TransitionState, request: WindowRequest) -> str:
    # 同一 state + config + input identity 必须产生相同 request_id（确定性）
    return _canonical_hash({"state": state_hash(state), "request": asdict(request)})
