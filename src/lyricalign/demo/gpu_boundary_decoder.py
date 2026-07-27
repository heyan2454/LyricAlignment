"""GPU-first sequence decoders for Qwen forced-alignment timestamp slots.

Two trainable architectures share one feature/cache contract:

* ``tcn``: residual dilated temporal convolutions.
* ``transformer``: bidirectional Transformer encoder over all timestamp slots.

All refinement, masking, and monotonic projection stay in PyTorch tensors.
Production entrypoints require CUDA by default; CPU is only for explicit tests.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
from typing import Any


FEATURE_SCHEMA = "qwen_fa_gpu_boundary_features_v1"
CHECKPOINT_SCHEMA = "qwen_fa_gpu_boundary_decoder_v2"
LEGACY_TCN_CHECKPOINT_SCHEMA = "qwen_fa_gpu_boundary_tcn_v1"
SUPPORTED_ARCHITECTURES = ("tcn", "transformer")


@dataclass(frozen=True)
class BoundaryDecoderConfig:
    architecture: str = "tcn"
    feature_dim: int = 16
    hidden_dim: int = 192
    layers: int = 6
    kernel_size: int = 5
    dropout: float = 0.10
    max_residual_classes: float = 96.0
    top_k: int = 4
    transformer_heads: int = 6
    transformer_ffn_dim: int = 768
    transformer_max_slots: int = 4096

    def validate(self) -> None:
        if self.architecture not in SUPPORTED_ARCHITECTURES:
            raise ValueError(f"unsupported decoder architecture: {self.architecture}")
        if self.feature_dim <= 0 or self.hidden_dim <= 0 or self.layers <= 0:
            raise ValueError("feature_dim, hidden_dim and layers must be positive")
        if self.architecture == "transformer":
            if self.transformer_heads <= 0 or self.hidden_dim % self.transformer_heads:
                raise ValueError("transformer hidden_dim must be divisible by transformer_heads")
            if self.transformer_ffn_dim < self.hidden_dim:
                raise ValueError("transformer_ffn_dim must be >= hidden_dim")
            if self.transformer_max_slots <= 0:
                raise ValueError("transformer_max_slots must be positive")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BoundaryDecoderConfig":
        keys = cls.__dataclass_fields__.keys()
        config = cls(**{key: payload[key] for key in keys if key in payload})
        config.validate()
        return config


class ResidualTCNBlock:
    """Factory wrapper to avoid importing torch at package import time."""

    @staticmethod
    def build(channels: int, kernel_size: int, dilation: int, dropout: float) -> Any:
        import torch.nn as nn

        padding = dilation * (kernel_size - 1) // 2
        return nn.Sequential(
            nn.Conv1d(channels, channels, kernel_size, padding=padding, dilation=dilation),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Conv1d(channels, channels, kernel_size, padding=padding, dilation=dilation),
            nn.GELU(),
            nn.Dropout(dropout),
        )


def _initialize_safe_heads(module: Any) -> None:
    """Make an untrained decoder approximately reproduce raw argmax."""
    import torch.nn as nn

    nn.init.zeros_(module.residual_head.weight)
    nn.init.zeros_(module.residual_head.bias)
    nn.init.zeros_(module.gate_head.weight)
    nn.init.constant_(module.gate_head.bias, -4.0)


def build_model(config: BoundaryDecoderConfig) -> Any:
    import torch
    import torch.nn as nn

    config.validate()

    class BoundaryTCN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.config = config
            self.input_projection = nn.Conv1d(config.feature_dim, config.hidden_dim, 1)
            self.blocks = nn.ModuleList(
                ResidualTCNBlock.build(
                    config.hidden_dim,
                    config.kernel_size,
                    2 ** (index % 5),
                    config.dropout,
                )
                for index in range(config.layers)
            )
            self.norm = nn.LayerNorm(config.hidden_dim)
            self.residual_head = nn.Linear(config.hidden_dim, 1)
            self.gate_head = nn.Linear(config.hidden_dim, 1)
            _initialize_safe_heads(self)

        def forward(self, features: torch.Tensor, mask: torch.Tensor | None = None) -> dict[str, torch.Tensor]:
            hidden = self.input_projection(features.transpose(1, 2))
            for block in self.blocks:
                hidden = hidden + block(hidden)
            hidden = self.norm(hidden.transpose(1, 2))
            residual = torch.tanh(self.residual_head(hidden).squeeze(-1)) * float(config.max_residual_classes)
            gate_logit = self.gate_head(hidden).squeeze(-1)
            if mask is not None:
                residual = residual.masked_fill(~mask, 0.0)
                gate_logit = gate_logit.masked_fill(~mask, -20.0)
            return {"residual_classes": residual, "gate_logit": gate_logit}

    class BoundaryTransformer(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.config = config
            self.input_projection = nn.Linear(config.feature_dim, config.hidden_dim)
            self.position_embedding = nn.Embedding(config.transformer_max_slots, config.hidden_dim)
            layer = nn.TransformerEncoderLayer(
                d_model=config.hidden_dim,
                nhead=config.transformer_heads,
                dim_feedforward=config.transformer_ffn_dim,
                dropout=config.dropout,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(layer, num_layers=config.layers, enable_nested_tensor=False)
            self.norm = nn.LayerNorm(config.hidden_dim)
            self.residual_head = nn.Linear(config.hidden_dim, 1)
            self.gate_head = nn.Linear(config.hidden_dim, 1)
            _initialize_safe_heads(self)

        def forward(self, features: torch.Tensor, mask: torch.Tensor | None = None) -> dict[str, torch.Tensor]:
            slots = int(features.shape[1])
            if slots > config.transformer_max_slots:
                raise ValueError(
                    f"slot count {slots} exceeds transformer_max_slots={config.transformer_max_slots}"
                )
            positions = torch.arange(slots, device=features.device)
            hidden = self.input_projection(features) + self.position_embedding(positions)[None, :, :]
            padding_mask = None if mask is None else ~mask
            hidden = self.encoder(hidden, src_key_padding_mask=padding_mask)
            hidden = self.norm(hidden)
            residual = torch.tanh(self.residual_head(hidden).squeeze(-1)) * float(config.max_residual_classes)
            gate_logit = self.gate_head(hidden).squeeze(-1)
            if mask is not None:
                residual = residual.masked_fill(~mask, 0.0)
                gate_logit = gate_logit.masked_fill(~mask, -20.0)
            return {"residual_classes": residual, "gate_logit": gate_logit}

    if config.architecture == "tcn":
        return BoundaryTCN()
    if config.architecture == "transformer":
        return BoundaryTransformer()
    raise AssertionError(config.architecture)


def _pad_topk(values: Any, indices: Any, top_k: int) -> tuple[Any, Any]:
    import torch

    current = int(values.shape[-1])
    if current == top_k:
        return values, indices
    if current > top_k:
        return values[..., :top_k], indices[..., :top_k]
    pad = top_k - current
    value_pad = torch.zeros((*values.shape[:-1], pad), device=values.device, dtype=values.dtype)
    index_pad = torch.zeros((*indices.shape[:-1], pad), device=indices.device, dtype=indices.dtype)
    return torch.cat([values, value_pad], dim=-1), torch.cat([indices, index_pad], dim=-1)


def build_slot_features(slot_logits: Any, *, top_k: int = 4) -> tuple[Any, dict[str, Any]]:
    """Build the fixed 16-D slot feature tensor entirely on the current device."""
    import torch

    if slot_logits.ndim != 2:
        raise ValueError(f"slot_logits must be [slots, classes], got {tuple(slot_logits.shape)}")
    slots, classes = int(slot_logits.shape[0]), int(slot_logits.shape[1])
    if slots < 2 or slots % 2:
        raise ValueError(f"timestamp slot count must be positive and even, got {slots}")
    probabilities = torch.softmax(slot_logits.float(), dim=-1)
    values, indices = torch.topk(probabilities, k=min(top_k, classes), dim=-1)
    values, indices = _pad_topk(values, indices, top_k)
    raw = indices[:, 0].float()
    class_denominator = float(max(1, classes - 1))
    position = torch.linspace(0.0, 1.0, slots, device=slot_logits.device, dtype=torch.float32)
    previous = torch.cat([raw[:1], raw[:-1]], dim=0)
    following = torch.cat([raw[1:], raw[-1:]], dim=0)
    pair_duration = torch.empty_like(raw)
    starts, ends = raw[0::2], raw[1::2]
    duration = ends - starts
    pair_duration[0::2] = duration
    pair_duration[1::2] = duration
    entropy = -(probabilities * probabilities.clamp_min(1e-12).log()).sum(dim=-1)
    entropy = entropy / max(1.0, math.log(float(classes)))
    slot_type = (torch.arange(slots, device=slot_logits.device) % 2).float()
    features = torch.cat(
        [
            indices.float() / class_denominator,
            values.float(),
            entropy[:, None],
            (values[:, 0] - values[:, 1])[:, None],
            slot_type[:, None],
            position[:, None],
            ((raw - previous) / class_denominator)[:, None],
            ((following - raw) / class_denominator)[:, None],
            (pair_duration / class_denominator)[:, None],
            ((raw / class_denominator) - position)[:, None],
        ],
        dim=-1,
    )
    if int(features.shape[-1]) != 16:
        raise RuntimeError(f"feature schema drift: expected 16, got {features.shape[-1]}")
    return features, {
        "raw_classes": raw.long(),
        "top_values": values,
        "top_indices": indices,
        "entropy": entropy,
        "num_classes": classes,
    }


def monotonic_project(classes: Any, *, mask: Any | None = None, maximum: int | None = None) -> Any:
    """GPU-vectorized nondecreasing projection for ordered start/end slots."""
    import torch

    if classes.ndim == 1:
        projected = torch.cummax(classes, dim=0).values
        if maximum is not None:
            projected = projected.clamp(0, maximum)
        return projected
    if classes.ndim != 2:
        raise ValueError("classes must have shape [slots] or [batch, slots]")
    work = classes
    if mask is not None:
        if mask.shape != classes.shape:
            raise ValueError("mask shape mismatch")
        sentinel = torch.full_like(work, -1e9)
        work = torch.where(mask, work, sentinel)
    projected = torch.cummax(work, dim=1).values
    if maximum is not None:
        projected = projected.clamp(0, maximum)
    if mask is not None:
        projected = torch.where(mask, projected, torch.zeros_like(projected))
    return projected


def predict_classes(model: Any, features: Any, raw_classes: Any, *, mask: Any | None = None, maximum: int) -> dict[str, Any]:
    import torch

    output = model(features, mask)
    gate = torch.sigmoid(output["gate_logit"])
    corrected = raw_classes.float() + gate * output["residual_classes"]
    projected = monotonic_project(corrected, mask=mask, maximum=maximum)
    return {
        **output,
        "gate": gate,
        "corrected_classes": corrected,
        "projected_classes": projected,
        "rounded_classes": projected.round().long(),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class GpuBoundaryDecoderRuntime:
    """Loaded TCN/Transformer checkpoint used by serial and local-realignment inference."""

    def __init__(self, checkpoint: Path, *, device: str = "cuda", allow_cpu: bool = False) -> None:
        import torch

        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        if not device.startswith("cuda") and not allow_cpu:
            raise RuntimeError("GPU boundary decoder requires CUDA; use allow_cpu only for explicit tests")
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested for the GPU boundary decoder but is unavailable")
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        schema = payload.get("schema_version")
        if schema not in {CHECKPOINT_SCHEMA, LEGACY_TCN_CHECKPOINT_SCHEMA}:
            raise ValueError(f"unsupported decoder checkpoint schema: {schema}")
        model_config = dict(payload["model_config"])
        if schema == LEGACY_TCN_CHECKPOINT_SCHEMA:
            model_config.setdefault("architecture", "tcn")
        self.config = BoundaryDecoderConfig.from_dict(model_config)
        self.model = build_model(self.config)
        self.model.load_state_dict(payload["model_state_dict"])
        self.device = device
        self.model.to(device).eval()
        self.identity = {
            "schema_version": schema,
            "checkpoint": str(checkpoint.resolve()),
            "checkpoint_sha256": _sha256_file(checkpoint),
            "architecture": self.config.architecture,
            "model_config": asdict(self.config),
            "training_step": payload.get("training_step"),
            "feature_schema": payload.get("feature_schema"),
        }

    def decode(self, slot_logits: Any) -> dict[str, Any]:
        import torch

        with torch.inference_mode():
            features, evidence = build_slot_features(slot_logits.to(self.device), top_k=self.config.top_k)
            raw = evidence["raw_classes"]
            predicted = predict_classes(
                self.model,
                features.unsqueeze(0),
                raw.unsqueeze(0),
                mask=torch.ones((1, len(raw)), dtype=torch.bool, device=self.device),
                maximum=int(evidence["num_classes"]) - 1,
            )
        return {
            "classes": predicted["rounded_classes"][0],
            "gate": predicted["gate"][0],
            "residual_classes": predicted["residual_classes"][0],
            "features": features,
            "raw_classes": raw,
        }


def save_checkpoint(
    path: Path,
    *,
    model: Any,
    config: BoundaryDecoderConfig,
    training_step: int,
    optimizer_state_dict: dict[str, Any] | None = None,
    scheduler_state_dict: dict[str, Any] | None = None,
    scaler_state_dict: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    import torch

    config.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": CHECKPOINT_SCHEMA,
        "feature_schema": FEATURE_SCHEMA,
        "model_config": asdict(config),
        "training_step": int(training_step),
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer_state_dict,
        "scheduler_state_dict": scheduler_state_dict,
        "scaler_state_dict": scaler_state_dict,
        "extra": extra or {},
    }
    torch.save(payload, temporary)
    temporary.replace(path)
