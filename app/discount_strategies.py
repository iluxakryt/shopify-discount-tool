# app/discount_strategies.py
from typing import Dict, Tuple, Optional
from enum import Enum

class DiscountStrategy(Enum):
    """Стратегії керування знижками"""
    INCREASE_COMPARE_ONLY = "increase_compare_only"      # Збільшити тільки compare_at_price (збільшити знижку)
    DECREASE_PRICE_ONLY = "decrease_price_only"          # Зменшити тільки price (збільшити знижку + зменшити ціну)
    BOTH_DIRECTIONS = "both_directions"                  # Змінити обидві ціни (максимальний контроль)
    SET_DISCOUNT_PERCENTAGE = "set_discount_percentage"   # Встановити конкретний відсоток знижки

class DiscountCalculator:
    """Калькулятор для різних стратегій знижок"""
    
    @staticmethod
    def calculate_new_prices(
        current_price: float,
        current_compare_at_price: Optional[float],
        strategy: DiscountStrategy,
        value: float,
        target_discount_percentage: Optional[float] = None
    ) -> Tuple[float, Optional[float]]:
        """
        Розраховує нові ціни на основі стратегії
        
        Args:
            current_price: Поточна ціна товару
            current_compare_at_price: Поточна порівняльна ціна (може бути None)
            strategy: Стратегія керування знижкою
            value: Значення для зміни (у відсотках)
            target_discount_percentage: Цільовий відсоток знижки (для SET_DISCOUNT_PERCENTAGE)
            
        Returns:
            Tuple[new_price, new_compare_at_price]
        """
        
        if strategy == DiscountStrategy.INCREASE_COMPARE_ONLY:
            # Збільшуємо тільки compare_at_price, price залишається без змін
            new_price = current_price
            
            if current_compare_at_price:
                # Збільшуємо існуючу порівняльну ціну
                new_compare_at_price = current_compare_at_price * (1 + value / 100)
            else:
                # Створюємо нову порівняльну ціну
                new_compare_at_price = current_price * (1 + value / 100)
            
            return new_price, new_compare_at_price
        
        elif strategy == DiscountStrategy.DECREASE_PRICE_ONLY:
            # Зменшуємо price, compare_at_price залишається або створюється
            new_price = current_price * (1 - abs(value) / 100)  # завжди зменшуємо
            
            if current_compare_at_price:
                new_compare_at_price = current_compare_at_price
            else:
                # Створюємо порівняльну ціну як стару ціну
                new_compare_at_price = current_price
            
            return new_price, new_compare_at_price
        
        elif strategy == DiscountStrategy.BOTH_DIRECTIONS:
            # Змінюємо обидві ціни
            new_price = current_price * (1 + value / 100)
            
            if current_compare_at_price:
                # Збільшуємо compare_at_price більше, ніж price
                compare_multiplier = 1 + (value * 1.5) / 100  # в 1.5 рази більша зміна
                new_compare_at_price = current_compare_at_price * compare_multiplier
            else:
                # Створюємо порівняльну ціну
                new_compare_at_price = current_price * (1 + abs(value * 2) / 100)
            
            return new_price, new_compare_at_price
        
        elif strategy == DiscountStrategy.SET_DISCOUNT_PERCENTAGE:
            # Встановлюємо конкретний відсоток знижки
            if target_discount_percentage is None:
                raise ValueError("target_discount_percentage обов'язковий для цієї стратегії")
            
            new_price = current_price
            # compare_at_price = price / (1 - discount_percentage/100)
            new_compare_at_price = current_price / (1 - target_discount_percentage / 100)
            
            return new_price, new_compare_at_price
        
        else:
            raise ValueError(f"Невідома стратегія: {strategy}")
    
    @staticmethod
    def calculate_discount_percentage(price: float, compare_at_price: float) -> float:
        """Розраховує відсоток знижки"""
        if compare_at_price <= price:
            return 0.0
        return ((compare_at_price - price) / compare_at_price) * 100
    
    @staticmethod
    def preview_discount_change(
        current_price: float,
        current_compare_at_price: Optional[float],
        strategy: DiscountStrategy,
        value: float,
        target_discount_percentage: Optional[float] = None
    ) -> Dict:
        """Створює приклад зміни знижки"""
        
        # Розраховуємо поточну знижку
        current_discount = 0.0
        if current_compare_at_price and current_compare_at_price > current_price:
            current_discount = DiscountCalculator.calculate_discount_percentage(
                current_price, current_compare_at_price
            )
        
        # Розраховуємо нові ціни
        new_price, new_compare_at_price = DiscountCalculator.calculate_new_prices(
            current_price, current_compare_at_price, strategy, value, target_discount_percentage
        )
        
        # Розраховуємо нову знижку
        new_discount = 0.0
        if new_compare_at_price and new_compare_at_price > new_price:
            new_discount = DiscountCalculator.calculate_discount_percentage(
                new_price, new_compare_at_price
            )
        
        return {
            'current_price': current_price,
            'current_compare_at_price': current_compare_at_price,
            'current_discount_percentage': round(current_discount, 2),
            'new_price': round(new_price, 2),
            'new_compare_at_price': round(new_compare_at_price, 2) if new_compare_at_price else None,
            'new_discount_percentage': round(new_discount, 2),
            'discount_change': round(new_discount - current_discount, 2),
            'strategy_description': DiscountCalculator.get_strategy_description(strategy)
        }
    
    @staticmethod
    def get_strategy_description(strategy: DiscountStrategy) -> str:
        """Опис стратегії українською"""
        descriptions = {
            DiscountStrategy.INCREASE_COMPARE_ONLY: "Збільшення тільки порівняльної ціни (збільшити знижку)",
            DiscountStrategy.DECREASE_PRICE_ONLY: "Зменшення тільки основної ціни (збільшити знижку + зменшити ціну)",
            DiscountStrategy.BOTH_DIRECTIONS: "Зміна обох цін (максимальний контроль знижки)",
            DiscountStrategy.SET_DISCOUNT_PERCENTAGE: "Встановлення конкретного відсотка знижки"
        }
        return descriptions.get(strategy, "Невідома стратегія")

# Приклади використання:

def example_usage():
    """Приклади використання різних стратегій"""
    
    # Поточні ціни товару
    current_price = 100.0
    current_compare_at_price = 120.0  # Поточна знижка 16.67%
    
    calculator = DiscountCalculator()
    
    print("=== ПОТОЧНИЙ СТАН ===")
    print(f"Ціна: ${current_price}")
    print(f"Порівняльна ціна: ${current_compare_at_price}")
    current_discount = calculator.calculate_discount_percentage(current_price, current_compare_at_price)
    print(f"Поточна знижка: {current_discount:.2f}%")
    print()
    
    # Стратегія 1: Збільшити тільки compare_at_price на 15%
    print("=== СТРАТЕГІЯ 1: Збільшити тільки порівняльну ціну ===")
    preview1 = calculator.preview_discount_change(
        current_price, current_compare_at_price, 
        DiscountStrategy.INCREASE_COMPARE_ONLY, 15
    )
    print(f"Нова ціна: ${preview1['new_price']}")
    print(f"Нова порівняльна ціна: ${preview1['new_compare_at_price']}")
    print(f"Нова знижка: {preview1['new_discount_percentage']:.2f}%")
    print(f"Зміна знижки: +{preview1['discount_change']:.2f}%")
    print()
    
    # Стратегія 2: Зменшити тільки price на 10%
    print("=== СТРАТЕГІЯ 2: Зменшити тільки основну ціну ===")
    preview2 = calculator.preview_discount_change(
        current_price, current_compare_at_price,
        DiscountStrategy.DECREASE_PRICE_ONLY, 10
    )
    print(f"Нова ціна: ${preview2['new_price']}")
    print(f"Нова порівняльна ціна: ${preview2['new_compare_at_price']}")
    print(f"Нова знижка: {preview2['new_discount_percentage']:.2f}%")
    print(f"Зміна знижки: +{preview2['discount_change']:.2f}%")
    print()
    
    # Стратегія 3: Встановити конкретну знижку 30%
    print("=== СТРАТЕГІЯ 3: Встановити знижку 30% ===")
    preview3 = calculator.preview_discount_change(
        current_price, current_compare_at_price,
        DiscountStrategy.SET_DISCOUNT_PERCENTAGE, 0, 30
    )
    print(f"Нова ціна: ${preview3['new_price']}")
    print(f"Нова порівняльна ціна: ${preview3['new_compare_at_price']}")
    print(f"Нова знижка: {preview3['new_discount_percentage']:.2f}%")
    print(f"Зміна знижки: +{preview3['discount_change']:.2f}%")

if __name__ == "__main__":
    example_usage()