from __future__ import annotations


class LocalAgentExtension:
    name = "local_agent"

    def is_available(self) -> bool:
        return False
