from __future__ import annotations

import numpy as np

from vibeflow.core import drums


def test_all_kits_produce_audible_distinct_buffers():
    for render in (drums.render_kick, drums.render_clap, drums.render_hat, drums.render_impact):
        buffers = {kit: render(kit) for kit in drums.KIT_LABELS}
        for kit, buffer in buffers.items():
            assert buffer.size > 100, kit
            assert np.isfinite(buffer).all(), kit
            assert float(np.max(np.abs(buffer))) > 0.01, kit
        signatures = {buffer[:4096].tobytes() for buffer in buffers.values()}
        assert len(signatures) == len(buffers)


def test_open_hat_is_longer_than_closed_hat():
    for kit in drums.KIT_LABELS:
        closed = drums.render_hat(kit, False)
        opened = drums.render_hat(kit, True)
        assert len(opened) > len(closed)
