import pytest

from rv_dashboard.operator_auth import OperatorPinGuard, hash_operator_pin, validate_operator_pin, verify_operator_pin


def test_operator_pin_hash_round_trip_and_wrong_pin_rejection():
    encoded = hash_operator_pin("4826")

    assert encoded.startswith("pbkdf2_sha256$")
    assert "4826" not in encoded
    assert verify_operator_pin("4826", encoded) is True
    assert verify_operator_pin("4827", encoded) is False


@pytest.mark.parametrize("pin", ["123", "1234567890123", "12a4", "１２３４"])
def test_operator_pin_validation_rejects_weak_shapes(pin: str):
    with pytest.raises(ValueError, match="4 through 12 digits"):
        validate_operator_pin(pin)


def test_operator_pin_verification_fails_closed_for_bad_hash():
    assert verify_operator_pin("4826", "") is False
    assert verify_operator_pin("4826", "pbkdf2_sha256$1$bad$bad") is False


def test_operator_pin_guard_locks_then_recovers_after_window():
    encoded = hash_operator_pin("4826")
    guard = OperatorPinGuard(maximum_failures=2, window_seconds=30)

    assert guard.check("0000", encoded, now=10) == "denied"
    assert guard.check("0000", encoded, now=11) == "denied"
    assert guard.check("4826", encoded, now=12) == "locked"
    assert guard.check("4826", encoded, now=41) == "allowed"
