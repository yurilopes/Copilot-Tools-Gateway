import base64

from copilot_tools_gateway.providers.consumer.challenges import solve_hashcash


def test_hashcash_accepts_plain_parameter() -> None:
    token = solve_hashcash("seed:0")

    assert token == "0"


def test_hashcash_accepts_base64url_parameter() -> None:
    parameter = base64.urlsafe_b64encode(b"seed:0").decode("ascii").rstrip("=")

    token = solve_hashcash(parameter)

    assert token == "0"
