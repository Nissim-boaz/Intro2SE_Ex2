import ipaddress
from pathlib import Path
from flask import Request, current_app
from config import Config

def _get_cfg(key, default=None):
    try:
        if current_app:
            return current_app.config.get(key, getattr(Config, key, default))
    except RuntimeError:
        pass
    return getattr(Config, key, default)

class CampusCheckService:
    @classmethod
    def load_campus_networks(cls) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """Loads allowed campus CIDR networks from config and file."""
        networks = []
        raw_ranges = list(_get_cfg("CAMPUS_IP_RANGES", Config.CAMPUS_IP_RANGES) or [])

        # Also load from file if specified
        ip_file_path = _get_cfg("CAMPUS_IP_FILE", Config.CAMPUS_IP_FILE)
        if ip_file_path:
            ip_file = Path(ip_file_path)
            if ip_file.is_file():
                try:
                    with open(ip_file, mode="r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                raw_ranges.append(line)
                except Exception:
                    pass

        for r in raw_ranges:
            try:
                net = ipaddress.ip_network(r.strip(), strict=False)
                networks.append(net)
            except ValueError:
                continue

        return networks

    @classmethod
    def get_client_ip(cls, request: Request) -> str:
        """Extracts the client's IP from request headers (handling reverse proxy) or remote_addr."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # First IP in X-Forwarded-For is the original client IP
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip
        return request.remote_addr or "127.0.0.1"

    @classmethod
    def is_campus_ip(cls, ip_str: str) -> bool:
        """
        Checks whether the given IP address falls within the campus ranges.
        Returns True if inside campus, False if outside (suspicious).
        """
        try:
            ip_obj = ipaddress.ip_address(ip_str.strip())
        except ValueError:
            return False

        networks = cls.load_campus_networks()
        for net in networks:
            if ip_obj in net:
                return True
        return False
