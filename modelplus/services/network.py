"""בדיקה אם כתובת IP שייכת לרשת הקמפוס, לפי רשימת CIDR בקובץ הגדרות."""
import ipaddress
from pathlib import Path


class CampusNetworkPolicy:
    def __init__(self, cidrs: list[str]):
        self.networks = [ipaddress.ip_network(c.strip(), strict=False) for c in cidrs if c.strip()]

    @classmethod
    def from_file(cls, path: str) -> "CampusNetworkPolicy":
        p = Path(path)
        if not p.exists():
            return cls([])
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        return cls([ln.split("#", 1)[0] for ln in lines if ln.split("#", 1)[0].strip()])

    @property
    def enabled(self) -> bool:
        return bool(self.networks)

    def is_campus(self, ip: str) -> bool:
        """אם לא הוגדרו טווחים, אף כתובת לא נחשבת חשודה."""
        if not self.enabled:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.networks)
