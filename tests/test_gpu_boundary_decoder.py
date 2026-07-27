from __future__ import annotations

from pathlib import Path

import pytest


torch = pytest.importorskip("torch")

from lyricalign.demo.gpu_boundary_decoder import (
    BoundaryDecoderConfig,
    GpuBoundaryDecoderRuntime,
    build_model,
    build_slot_features,
    monotonic_project,
    save_checkpoint,
)


def test_slot_features_are_fixed_width_and_gpu_vectorizable() -> None:
    logits = torch.randn(10, 32)
    features, evidence = build_slot_features(logits)
    assert features.shape == (10, 16)
    assert evidence["raw_classes"].shape == (10,)
    assert torch.isfinite(features).all()


def test_monotonic_projection_preserves_mask_and_order() -> None:
    values = torch.tensor([[4.0, 2.0, 3.0, 8.0, 0.0]])
    mask = torch.tensor([[True, True, True, True, False]])
    projected = monotonic_project(values, mask=mask, maximum=9)
    assert projected[0, :4].tolist() == [4.0, 4.0, 4.0, 8.0]
    assert projected[0, 4].item() == 0.0


@pytest.mark.parametrize(
    "config",
    [
        BoundaryDecoderConfig(architecture="tcn", hidden_dim=16, layers=2, kernel_size=3),
        BoundaryDecoderConfig(
            architecture="transformer",
            hidden_dim=24,
            layers=2,
            transformer_heads=4,
            transformer_ffn_dim=48,
            transformer_max_slots=64,
        ),
    ],
)
def test_checkpoint_runtime_can_decode_both_architectures_on_explicit_cpu_test(
    tmp_path: Path,
    config: BoundaryDecoderConfig,
) -> None:
    model = build_model(config)
    checkpoint = tmp_path / f"{config.architecture}.pt"
    save_checkpoint(checkpoint, model=model, config=config, training_step=3)
    runtime = GpuBoundaryDecoderRuntime(checkpoint, device="cpu", allow_cpu=True)
    output = runtime.decode(torch.randn(8, 40))
    classes = output["classes"]
    assert runtime.identity["architecture"] == config.architecture
    assert classes.shape == (8,)
    assert torch.all(classes[1:] >= classes[:-1])


def test_transformer_masks_padded_slots() -> None:
    config = BoundaryDecoderConfig(
        architecture="transformer",
        hidden_dim=24,
        layers=1,
        transformer_heads=4,
        transformer_ffn_dim=48,
        transformer_max_slots=64,
    )
    model = build_model(config)
    features = torch.randn(2, 10, 16)
    mask = torch.tensor([[True] * 10, [True] * 6 + [False] * 4])
    output = model(features, mask)
    assert output["residual_classes"][1, 6:].eq(0).all()
    assert output["gate_logit"][1, 6:].lt(-10).all()
