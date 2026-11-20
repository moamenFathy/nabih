"""
Circuit Breaker & Fallback Resilience Monitor for Project Nabih.
Tracks service failure and fallback counts across external providers (Gemini, Sovereign, Groq).
When consecutive failures exceed a threshold, trips into an OPEN state to immediately
bypass the broken service, eliminating timeout latency and preventing redundant API calls.
"""

import time
from typing import Dict, Any, Optional
from loguru import logger


class ServiceCircuitBreaker:
    """
    Monitors consecutive failures and trips to OPEN state when a service goes down,
    routing requests immediately to the fallback provider.
    """

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 3,
        recovery_timeout_s: float = 120.0,
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s

        self.consecutive_failures: int = 0
        self.total_fallbacks: int = 0
        self.total_successes: int = 0
        self.last_failure_time: float = 0.0
        self.last_failure_reason: str = ""
        self.state: str = "CLOSED"  # CLOSED = Healthy, OPEN = Tripped (Bypassed), HALF_OPEN = Probing

    def record_success(self):
        """Records a successful primary call and resets the circuit to CLOSED."""
        self.total_successes += 1
        if self.state != "CLOSED":
            logger.info(
                f"[CIRCUIT BREAKER] 🟢 {self.service_name} has recovered! "
                f"Resetting state from {self.state} to CLOSED."
            )
        self.consecutive_failures = 0
        self.state = "CLOSED"

    def record_fallback(self, reason: str):
        """Records a failure/fallback event and trips to OPEN if threshold is reached."""
        self.total_fallbacks += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        self.last_failure_reason = reason

        logger.warning(
            f"[CIRCUIT BREAKER] ⚠️ {self.service_name} fallback triggered "
            f"(Turn Fallbacks: {self.total_fallbacks} | Consecutive: {self.consecutive_failures}/{self.failure_threshold}) "
            f"Reason: {reason}"
        )

        if self.consecutive_failures >= self.failure_threshold:
            if self.state != "OPEN":
                logger.error(
                    f"[CIRCUIT BREAKER] 🔴 {self.service_name} circuit TRIPPED to OPEN! "
                    f"Service failed {self.consecutive_failures} consecutive times. "
                    f"Bypassing directly to fallback provider for {self.recovery_timeout_s}s to eliminate latency."
                )
            self.state = "OPEN"

    def should_attempt_primary(self) -> bool:
        """Determines if the primary service should be attempted or bypassed."""
        if self.state == "CLOSED":
            return True

        # If OPEN, check if recovery cooldown elapsed to probe (HALF_OPEN)
        if time.time() - self.last_failure_time > self.recovery_timeout_s:
            logger.info(
                f"[CIRCUIT BREAKER] 🟡 {self.service_name} cooldown elapsed ({self.recovery_timeout_s}s). "
                f"Probing primary service (HALF_OPEN)..."
            )
            self.state = "HALF_OPEN"
            return True

        # Still OPEN: Bypass immediately to fallback
        return False

    def get_status_summary(self) -> Dict[str, Any]:
        """Returns diagnostic metrics for telemetry and dashboard reporting."""
        return {
            "service": self.service_name,
            "state": self.state,
            "total_fallbacks": self.total_fallbacks,
            "consecutive_failures": self.consecutive_failures,
            "threshold": self.failure_threshold,
            "last_reason": self.last_failure_reason,
            "is_bypassed": self.state == "OPEN",
        }
