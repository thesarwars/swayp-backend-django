from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class BillCategoryResponseDTO:
    id: UUID
    name: str
    icon: str
    color: str
    displayOrder: int

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "displayOrder": self.displayOrder,
        }