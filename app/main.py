# app/main.py
from fastapi import FastAPI, BackgroundTasks, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio
from typing import Optional
import time
from datetime import datetime
import os
from dotenv import load_dotenv

# Завантажуємо змінні середовища
load_dotenv()

from .database import DatabaseManager
from .shopify_client import ShopifyClient
from .discount_strategies import DiscountStrategy, DiscountCalculator

app = FastAPI(title="Shopify Price Updater", version="2.0.0")

# Налаштування статичних файлів та шаблонів
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Глобальні екземпляри
db_manager = DatabaseManager()
shopify_client = ShopifyClient()
discount_calculator = DiscountCalculator()

# Зберігання прогресу завдань
task_progress = {}

@app.on_event("startup")
async def startup_event():
    """Ініціалізація при запуску програми"""
    await db_manager.initialize()
    print("✅ База даних ініціалізована")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Головна сторінка з формою оновлення цін"""
    recent_changes = await db_manager.get_recent_price_changes(limit=10)
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "recent_changes": recent_changes
    })

@app.get("/api/collections")
async def get_collections():
    """Отримати список всіх колекцій"""
    try:
        collections = await shopify_client.get_all_collections()
        return {
            "success": True,
            "collections": collections,
            "count": len(collections)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e), 
            "collections": []
        }

@app.get("/api/products")
async def get_products_info():
    """Отримати інформацію про товари для налагодження"""
    try:
        products = await shopify_client.get_products(limit=5)
        
        # Збираємо унікальні типи товарів та виробників
        product_types = set()
        vendors = set()
        
        for product in products:
            if product.get('product_type'):
                product_types.add(product['product_type'])
            if product.get('vendor'):
                vendors.add(product['vendor'])
        
        return {
            "success": True,
            "sample_products": products[:3],  # Перші 3 товари як приклад
            "total_found": len(products),
            "available_product_types": list(product_types),
            "available_vendors": list(vendors)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/preview-changes")
async def preview_changes(
    strategy: str = Form(...),
    value: float = Form(...),
    target_discount: Optional[float] = Form(None),
    filter_type: str = Form("all"),
    filter_value: Optional[str] = Form(None)
):
    """Показуємо приклад того, як зміняться ціни та знижки"""
    try:
        print(f"=== PREVIEW DEBUG ===")
        print(f"Strategy: {strategy}")
        print(f"Value: {value}")
        print(f"Filter type: {filter_type}")
        print(f"Filter value: {filter_value}")
        
        # Конвертуємо стратегію
        discount_strategy = DiscountStrategy(strategy)
        
        # Отримуємо один товар для прикладу
        products = await get_filtered_products(filter_type, filter_value, limit=1)
        print(f"Знайдено товарів: {len(products)}")
        
        if not products:
            return {"error": "Не знайдено товарів за вказаними критеріями"}
        
        product = products[0]
        variant = product['variants'][0] if product.get('variants') else None
        
        if not variant:
            return {"error": "У товару немає варіантів"}
        
        print(f"Товар: {product['title']}")
        print(f"Поточна ціна: {variant['price']}")
        print(f"Поточна порівняльна ціна: {variant.get('compare_at_price')}")
        
        # Поточні ціни
        current_price = float(variant['price'])
        current_compare_at_price = float(variant['compare_at_price']) if variant.get('compare_at_price') else None
        
        # Створюємо приклад зміни
        preview = discount_calculator.preview_discount_change(
            current_price, current_compare_at_price, 
            discount_strategy, value, target_discount
        )
        
        # Додаємо інформацію про товар
        preview.update({
            'product_title': product['title'],
            'variant_title': variant.get('title', 'За замовчуванням'),
            'savings_amount': (preview['new_compare_at_price'] or 0) - preview['new_price']
        })
        
        print(f"Preview результат: {preview}")
        return preview
        
    except Exception as e:
        print(f"ПОМИЛКА В PREVIEW: {str(e)}")
        return {"error": f"Помилка створення прикладу: {str(e)}"}

@app.post("/update-prices")
async def update_prices(
    background_tasks: BackgroundTasks,
    strategy: str = Form(...),
    value: float = Form(...),
    target_discount: Optional[float] = Form(None),
    filter_type: str = Form("all"),
    filter_value: Optional[str] = Form(None),
    limit_products: Optional[int] = Form(None)
):
    """Запускаємо масове оновлення цін з новими стратегіями"""
    
    try:
        discount_strategy = DiscountStrategy(strategy)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невірна стратегія знижки")
    
    # Створюємо сесію для можливості відкату
    strategy_description = discount_calculator.get_strategy_description(discount_strategy)
    session_id = await db_manager.create_rollback_session(
        "DISCOUNT_UPDATE", 
        f"{strategy_description} - значення: {value}%"
    )
    
    # Запускаємо завдання у фоні
    task_id = f"discount_update_{int(time.time())}"
    background_tasks.add_task(
        process_discount_update,
        task_id,
        session_id,
        discount_strategy,
        value,
        target_discount,
        filter_type,
        filter_value,
        limit_products
    )
    
    return {
        "task_id": task_id, 
        "session_id": session_id, 
        "status": "started",
        "message": f"Оновлення знижок розпочато: {strategy_description}"
    }

@app.get("/progress/{task_id}")
async def get_progress(task_id: str):
    """Отримуємо прогрес виконання завдання"""
    progress_data = task_progress.get(task_id)
    
    if not progress_data:
        raise HTTPException(status_code=404, detail="Завдання не знайдено")
    
    return progress_data

async def get_filtered_products(filter_type: str, filter_value: Optional[str], limit: Optional[int] = None):
    """Отримуємо товари за фільтрами"""
    
    print(f"=== FILTER DEBUG ===")
    print(f"Filter type: {filter_type}")
    print(f"Filter value: {filter_value}")
    print(f"Limit: {limit}")
    
    try:
        if filter_type == "all":
            products = await shopify_client.get_products(limit=limit or 250)
            print(f"Отримано всіх товарів: {len(products)}")
        
        elif filter_type == "collection":
            # Використовуємо новий розумний метод
            products = await shopify_client.get_products_by_collection_smart(filter_value, limit=limit or 250)
            print(f"Отримано товарів з колекції '{filter_value}': {len(products)}")
        
        elif filter_type == "product_type":
            products = await shopify_client.get_products(
                limit=limit or 250,
                product_type=filter_value
            )
            print(f"Отримано товарів за типом '{filter_value}': {len(products)}")
        
        elif filter_type == "vendor":
            products = await shopify_client.get_products(
                limit=limit or 250,
                vendor=filter_value
            )
            print(f"Отримано товарів за виробником '{filter_value}': {len(products)}")
        
        else:
            print(f"Невідомий тип фільтру: {filter_type}")
            products = []
        
        print(f"=== КІНЕЦЬ FILTER DEBUG ===")
        return products
        
    except Exception as e:
        print(f"ПОМИЛКА В ФІЛЬТРІ: {str(e)}")
        return []

async def process_discount_update(
    task_id: str,
    session_id: str,
    strategy: DiscountStrategy,
    value: float,
    target_discount: Optional[float],
    filter_type: str,
    filter_value: Optional[str],
    limit_products: Optional[int]
):
    """Обробляємо масове оновлення знижок"""
    
    try:
        # Ініціалізуємо прогрес
        task_progress[task_id] = {
            'status': 'initializing',
            'current': 0,
            'total': 0,
            'percentage': 0,
            'current_item': None,
            'errors': [],
            'session_id': session_id,
            'strategy': strategy.value
        }
        
        # Отримуємо товари для оновлення
        products = await get_filtered_products(filter_type, filter_value, limit_products)
        
        # Підраховуємо загальну кількість варіантів
        total_variants = sum(len(p.get('variants', [])) for p in products)
        
        task_progress[task_id].update({
            'total': total_variants,
            'status': 'processing'
        })
        
        # Обробляємо кожен товар
        current = 0
        successful_updates = 0
        
        for product in products:
            for variant in product.get('variants', []):
                try:
                    success = await update_single_variant_discount(
                        product,
                        variant,
                        strategy,
                        value,
                        target_discount,
                        session_id
                    )
                    
                    if success:
                        successful_updates += 1
                    
                    current += 1
                    
                    # Оновлюємо прогрес
                    task_progress[task_id].update({
                        'current': current,
                        'successful': successful_updates,
                        'percentage': int((current / total_variants) * 100),
                        'current_item': f"{product['title']} - {variant.get('title', 'За замовчуванням')}"
                    })
                    
                    # Невелика затримка для уникнення перевантаження API
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    task_progress[task_id]['errors'].append({
                        'product': product['title'],
                        'variant_id': variant['id'],
                        'error': str(e)
                    })
        
        # Завершуємо завдання
        task_progress[task_id].update({
            'status': 'completed',
            'completed_at': datetime.now().isoformat(),
            'final_stats': {
                'total_processed': current,
                'successful_updates': successful_updates,
                'errors_count': len(task_progress[task_id]['errors'])
            }
        })
        
    except Exception as e:
        task_progress[task_id].update({
            'status': 'failed',
            'error': str(e)
        })

async def update_single_variant_discount(
    product: dict,
    variant: dict,
    strategy: DiscountStrategy,
    value: float,
    target_discount: Optional[float],
    session_id: str
) -> bool:
    """Оновлюємо знижку одного варіанту товару"""
    
    try:
        # Поточні ціни
        current_price = float(variant['price'])
        current_compare_at_price = float(variant['compare_at_price']) if variant.get('compare_at_price') else None
        
        # Розраховуємо нові ціни
        new_price, new_compare_at_price = discount_calculator.calculate_new_prices(
            current_price, current_compare_at_price, strategy, value, target_discount
        )
        
        # Оновлюємо через Shopify API
        await shopify_client.update_variant_price(
            variant['id'],
            f"{new_price:.2f}",
            f"{new_compare_at_price:.2f}" if new_compare_at_price else None
        )
        
        # Розраховуємо знижки для логування
        old_discount = 0
        if current_compare_at_price and current_compare_at_price > current_price:
            old_discount = discount_calculator.calculate_discount_percentage(current_price, current_compare_at_price)
        
        new_discount = 0
        if new_compare_at_price and new_compare_at_price > new_price:
            new_discount = discount_calculator.calculate_discount_percentage(new_price, new_compare_at_price)
        
        # Зберігаємо зміну в історію
        await db_manager.log_price_change({
            'product_id': product['id'],
            'variant_id': variant['id'],
            'old_price': current_price,
            'new_price': new_price,
            'old_compare_at_price': current_compare_at_price,
            'new_compare_at_price': new_compare_at_price,
            'change_type': 'DISCOUNT_UPDATE',
            'session_id': session_id,
            'notes': f"Стратегія: {strategy.value}, Стара знижка: {old_discount:.2f}%, Нова знижка: {new_discount:.2f}%",
            'rollback_data': {
                'variant_id': variant['id'],
                'restore_price': current_price,
                'restore_compare_at_price': current_compare_at_price,
                'old_discount_percentage': old_discount,
                'new_discount_percentage': new_discount
            }
        })
        
        return True
        
    except Exception as e:
        print(f"Помилка оновлення варіанту {variant['id']}: {str(e)}")
        return False

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)