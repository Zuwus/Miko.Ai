from __future__ import annotations


class DeveloperModeExtension:
    name = "developer_mode"

    def is_available(self) -> bool:
        return False
