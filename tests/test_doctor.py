import json

from copilot_tools_gateway.doctor import doctor_report
from copilot_tools_gateway.settings import GatewayPaths


def test_doctor_report_is_safe(tmp_path) -> None:
    paths = GatewayPaths.from_cwd(tmp_path)

    report = doctor_report(paths)
    serialized = json.dumps(report).lower()

    assert "dependencies" in report
    assert "session_files" in report
    assert "provider_status" in report
    assert "token" not in serialized
    assert "cookie" not in serialized
    assert "authorization" not in serialized
    assert "browser storage" not in serialized
