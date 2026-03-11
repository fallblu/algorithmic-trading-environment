"""Tests for ParameterGrid in execution/batch.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from execution.batch import ParameterGrid


class TestParameterGrid:
    def test_cartesian_product_two_params(self):
        """Two params with 2 and 3 values should produce 6 combinations."""
        grid = ParameterGrid(params={
            "fast": [5, 10],
            "slow": [20, 30, 40],
        })
        combos = grid.combinations()

        assert len(combos) == 6
        assert grid.total == 6

        # Every combination should have both keys
        for c in combos:
            assert "fast" in c
            assert "slow" in c

        # Verify specific expected combos exist
        assert {"fast": 5, "slow": 20} in combos
        assert {"fast": 10, "slow": 40} in combos

    def test_single_param(self):
        """A single parameter should produce one combo per value."""
        grid = ParameterGrid(params={"threshold": [0.1, 0.2, 0.3]})
        combos = grid.combinations()

        assert len(combos) == 3
        assert grid.total == 3
        assert combos == [
            {"threshold": 0.1},
            {"threshold": 0.2},
            {"threshold": 0.3},
        ]

    def test_multiple_params_three_way(self):
        """Three params should produce the full Cartesian product."""
        grid = ParameterGrid(params={
            "a": [1, 2],
            "b": [10, 20],
            "c": ["x", "y"],
        })
        combos = grid.combinations()

        assert len(combos) == 8
        assert grid.total == 8

        # Spot-check a few
        assert {"a": 1, "b": 10, "c": "x"} in combos
        assert {"a": 2, "b": 20, "c": "y"} in combos

    def test_empty_grid(self):
        """An empty grid should produce no combinations."""
        grid = ParameterGrid(params={})
        assert grid.combinations() == []
        assert grid.total == 0
