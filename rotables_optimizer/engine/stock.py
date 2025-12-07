from dataclasses import dataclass


@dataclass
class StockLevels:
    """Represents immediately usable kits at an airport."""

    first_class: int = 0
    business_class: int = 0
    premium_economy: int = 0
    economy: int = 0

    def clamp_non_negative(self):
        """Ensure no field drops below zero after arithmetic."""
        self.first_class = max(0, self.first_class)
        self.business_class = max(0, self.business_class)
        self.premium_economy = max(0, self.premium_economy)
        self.economy = max(0, self.economy)
