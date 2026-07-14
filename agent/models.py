import hashlib
from dataclasses import dataclass, field


@dataclass
class Job:
    title: str
    company: str
    url: str
    source: str
    location: str = ""
    posted_at: str = ""  # ISO date string when known
    terms: list = field(default_factory=list)

    @property
    def uid(self) -> str:
        return hashlib.sha1(f"{self.company}|{self.title}|{self.url}".lower().encode()).hexdigest()[:16]
