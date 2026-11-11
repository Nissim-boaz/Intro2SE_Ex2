from modules.campus_check.service import CampusCheckService

def test_campus_ip_detection(app):
    with app.app_context():
        # Inside campus ranges: 127.0.0.1, 192.168.1.50, 10.5.1.2
        assert CampusCheckService.is_campus_ip("127.0.0.1") is True
        assert CampusCheckService.is_campus_ip("192.168.1.55") is True
        assert CampusCheckService.is_campus_ip("10.200.1.5") is True

        # Outside campus ranges:
        assert CampusCheckService.is_campus_ip("8.8.8.8") is False
        assert CampusCheckService.is_campus_ip("203.0.113.195") is False
        assert CampusCheckService.is_campus_ip("192.168.2.1") is False

def test_client_ip_extraction_forwarded_for(app):
    class DummyRequest:
        headers = {"X-Forwarded-For": "203.0.113.195, 10.0.0.1"}
        remote_addr = "127.0.0.1"

    req = DummyRequest()
    client_ip = CampusCheckService.get_client_ip(req)
    assert client_ip == "203.0.113.195"
