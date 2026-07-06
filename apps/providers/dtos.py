from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class ProviderResponseDTO:
    id: UUID
    categoryId: UUID
    categoryName: str
    providerName: str
    providerCode: str
    logo: str
    description: Optional[str]
    country: str
    supportsAutoPay: bool

    def to_dict(self):
        return {
            "id": str(self.id),
            "categoryId": str(self.categoryId),
            "categoryName": self.categoryName,
            "providerName": self.providerName,
            "providerCode": self.providerCode,
            "logo": self.logo,
            "description": self.description,
            "country": self.country,
            "supportsAutoPay": self.supportsAutoPay,
        }