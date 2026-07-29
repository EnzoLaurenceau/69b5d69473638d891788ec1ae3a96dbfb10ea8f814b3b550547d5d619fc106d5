"""
Ratchet Optimizer Module for La Forge
=====================================
Implements the metrics-driven autonomous research and tuning ratchet loop
inspired by karpathy/autoresearch. Keeps improvements, rolls back regressions.

NMP: TOOL|INDEX|ratchet_optimizer|savings=65|pattern=ratchet tuning loop|approach=Optimize code/config iteratively, rollback on metric regression
"""

import time
import logging
from typing import Callable, Dict, Any, Tuple, Optional

logger = logging.getLogger("LaForge.Ratchet")


class RatchetOptimizer:
    """
    Executes a metrics-driven ratchet loop on a code snippet or configuration.
    Keeps changes that improve scores, discards/rolls back regressions.
    """

    def __init__(self, max_iterations: int = 10):
        self.max_iterations = max_iterations
        self.history = []

    def run_optimization(
        self,
        initial_state: str,
        mutate_fn: Callable[[str, int], str],
        eval_fn: Callable[[str], Tuple[float, bool]],  # Returns (score, is_valid)
        on_step_callback: Optional[Callable[[int, float, str, bool], None]] = None
    ) -> Tuple[str, float, list]:
        """
        Runs the ratchet loop.
        - mutate_fn: receives (current_state, iteration_index) and returns proposed mutation.
        - eval_fn: receives state and returns (score, is_valid).
        """
        current_state = initial_state
        current_score, is_valid = eval_fn(current_state)
        
        if not is_valid:
            logger.warning("Initial state is invalid. Starting ratchet loop anyway.")
            
        self.history.append({
            "iteration": 0,
            "score": current_score,
            "state": current_state,
            "accepted": True
        })

        for i in range(1, self.max_iterations + 1):
            # Propose mutation
            proposed_state = mutate_fn(current_state, i)
            
            # Evaluate proposed state
            try:
                score, valid = eval_fn(proposed_state)
            except Exception as e:
                logger.error(f"Iteration {i} evaluation crashed: {e}")
                score, valid = -99999.0, False

            accepted = False
            # Ratchet logic: must be valid and score must improve strictly
            if valid and score > current_score:
                current_state = proposed_state
                current_score = score
                accepted = True

            self.history.append({
                "iteration": i,
                "score": score,
                "state": proposed_state,
                "accepted": accepted
            })

            if on_step_callback:
                on_step_callback(i, score, proposed_state, accepted)

            logger.info(f"Ratchet Loop Iteration {i}: Score={score:.4f} (Valid={valid}). Accepted={accepted}. Best Score={current_score:.4f}")

        return current_state, current_score, self.history

    def to_nmp(self) -> str:
        return f"RATCHET|OPTIMIZER|max_iter={self.max_iterations}|history_len={len(self.history)}"
