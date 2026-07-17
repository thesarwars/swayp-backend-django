from integrations.directory.base import DirectoryProvider, DirectoryVendor

_CANNED = (
    DirectoryVendor("dir-att", "AT&T Business", "Telecom", True, "Same day"),
    DirectoryVendor("dir-comcast", "Comcast Business", "Telecom", True, "Same day"),
    DirectoryVendor("dir-verizon", "Verizon Business", "Telecom", True, "Same day"),
    DirectoryVendor("dir-aws", "Amazon Web Services", "SaaS", True, "Same day"),
)


class MockDirectoryProvider(DirectoryProvider):
    """Deterministic substring search over a few canned verified vendors."""

    name = "mock"

    def search(self, *, query: str) -> tuple[DirectoryVendor, ...]:
        q = (query or "").strip().lower()
        if not q:
            return ()
        return tuple(v for v in _CANNED if q in v.name.lower())
