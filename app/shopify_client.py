# app/shopify_client.py
import httpx
import asyncio
import time
from typing import List, Dict, Optional
import os

class ShopifyClient:
    def __init__(self):
        self.shop_url = os.getenv('SHOPIFY_SHOP_URL')
        self.access_token = os.getenv('SHOPIFY_ACCESS_TOKEN')
        self.api_version = "2024-04"
        self.base_url = f"https://{self.shop_url}/admin/api/{self.api_version}"
        
        # Обмеження швидкості запитів (щоб не перевищити ліміти Shopify)
        self.last_request_time = 0
        self.min_request_interval = 0.67  # ~1.5 запитів на секунду
        
    async def _make_request(self, method: str, endpoint: str, **kwargs):
        """Робимо запит до API з обмеженням швидкості"""
        # Забезпечуємо обмеження швидкості
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_request_interval:
            await asyncio.sleep(self.min_request_interval - time_since_last)
        
        headers = {
            'X-Shopify-Access-Token': self.access_token,
            'Content-Type': 'application/json'
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, f"{self.base_url}/{endpoint}", 
                headers=headers, **kwargs
            )
            
            self.last_request_time = time.time()
            
            # Обробляємо помилки
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 1))
                await asyncio.sleep(retry_after)
                return await self._make_request(method, endpoint, **kwargs)
            
            response.raise_for_status()
            return response.json()
    
    async def get_products(self, limit: int = 250, **filters) -> List[Dict]:
        """Отримуємо список товарів з фільтрами"""
        params = {'limit': limit, **filters}
        response = await self._make_request('GET', 'products.json', params=params)
        return response.get('products', [])
    
    async def get_products_by_collection(self, collection_id: int, limit: int = 250) -> List[Dict]:
        """Отримуємо товари з конкретної колекції за ID"""
        try:
            response = await self._make_request(
                'GET', f'collections/{collection_id}/products.json', 
                params={'limit': limit}
            )
            return response.get('products', [])
        except Exception as e:
            print(f"Помилка отримання товарів колекції {collection_id}: {e}")
            return []
    
    async def get_products_by_collection_handle(self, collection_handle: str, limit: int = 250) -> List[Dict]:
        """Отримуємо товари за handle колекції"""
        try:
            endpoint = f"collections/{collection_handle}/products.json"
            response = await self._make_request('GET', endpoint, params={'limit': limit})
            return response.get('products', [])
        except Exception as e:
            print(f"Handle помилка для '{collection_handle}': {e}")
            return []
    
    async def get_all_collections(self) -> List[Dict]:
        """Універсальний метод отримання всіх колекцій"""
        print("=== ПОЧАТОК ПОШУКУ КОЛЕКЦІЙ ===")
        
        # Метод 1: Спробуємо через звичайний REST API
        try:
            print("Спроба 1: REST API collections.json")
            response = await self._make_request('GET', 'collections.json')
            collections = response.get('collections', [])
            if collections:
                print(f"✅ REST API: знайдено {len(collections)} колекцій")
                return collections
            else:
                print("❌ REST API: колекції порожні")
        except Exception as e:
            print(f"❌ REST API помилка: {e}")
        
        # Метод 2: Через GraphQL Admin API
        try:
            print("Спроба 2: GraphQL Admin API")
            collections = await self.get_collections_via_graphql()
            if collections:
                print(f"✅ GraphQL Admin: знайдено {len(collections)} колекцій")
                return collections
            else:
                print("❌ GraphQL Admin: колекції порожні")
        except Exception as e:
            print(f"❌ GraphQL Admin помилка: {e}")
        
        # Метод 3: Через публічні ендпоінти (без API ключа)
        try:
            print("Спроба 3: Публічний JSON ендпоінт")
            collections = await self.get_collections_via_public_json()
            if collections:
                print(f"✅ Публічний API: знайдено {len(collections)} колекцій")
                return collections
        except Exception as e:
            print(f"❌ Публічний API помилка: {e}")
        
        # Метод 4: Через аналіз товарів (якщо товари мають collection_id)
        try:
            print("Спроба 4: Аналіз товарів для знаходження колекцій")
            collections = await self.discover_collections_from_products()
            if collections:
                print(f"✅ Через товари: знайдено {len(collections)} колекцій")
                return collections
        except Exception as e:
            print(f"❌ Через товари помилка: {e}")
        
        print("❌ Всі методи не спрацювали")
        return []
    
    async def get_collections_via_graphql(self) -> List[Dict]:
        """Отримуємо колекції через GraphQL API"""
        try:
            query = """
            {
              collections(first: 50) {
                edges {
                  node {
                    id
                    title
                    handle
                    productsCount
                  }
                }
              }
            }
            """
            
            response = await self._make_request(
                'POST', 
                'graphql.json',
                json={'query': query}
            )
            
            collections = []
            edges = response.get('data', {}).get('collections', {}).get('edges', [])
            
            for edge in edges:
                node = edge['node']
                # Конвертуємо GraphQL ID в число
                gql_id = node['id']
                numeric_id = gql_id.split('/')[-1] if '/' in gql_id else gql_id
                
                collections.append({
                    'id': int(numeric_id),
                    'title': node['title'],
                    'handle': node['handle'],
                    'products_count': node.get('productsCount', 0)
                })
            
            print(f"GraphQL знайшов {len(collections)} колекцій")
            return collections
            
        except Exception as e:
            print(f"GraphQL помилка: {e}")
            return []
    
    async def get_collections_via_public_json(self) -> List[Dict]:
        """Отримуємо колекції через публічний JSON ендпоінт"""
        try:
            # Публічний ендпоінт (без авторизації)
            public_url = f"https://{self.shop_url}/collections.json"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(public_url)
                
                if response.status_code == 200:
                    data = response.json()
                    collections = data.get('collections', [])
                    
                    # Форматуємо під наш стандарт
                    formatted_collections = []
                    for col in collections:
                        formatted_collections.append({
                            'id': col.get('id'),
                            'title': col.get('title'),
                            'handle': col.get('handle'),
                            'updated_at': col.get('updated_at')
                        })
                    
                    return formatted_collections
                else:
                    print(f"Публічний JSON код: {response.status_code}")
                    return []
                    
        except Exception as e:
            print(f"Публічний JSON помилка: {e}")
            return []
    
    async def discover_collections_from_products(self) -> List[Dict]:
        """Знаходимо колекції аналізуючи товари"""
        try:
            # Отримуємо товари з детальною інформацією
            products = await self.get_products(limit=250)
            collection_ids = set()
            
            # Збираємо всі унікальні collection_id з товарів
            for product in products:
                # Деякі товари можуть мати collection_id в метаданих
                if 'collection_id' in product:
                    collection_ids.add(product['collection_id'])
                
                # Або в варіантах
                for variant in product.get('variants', []):
                    if 'collection_id' in variant:
                        collection_ids.add(variant['collection_id'])
            
            # Пробуємо отримати деталі кожної колекції
            collections = []
            for col_id in collection_ids:
                try:
                    response = await self._make_request('GET', f'collections/{col_id}.json')
                    collection = response.get('collection', {})
                    if collection:
                        collections.append(collection)
                except:
                    continue
            
            return collections
            
        except Exception as e:
            print(f"Discover помилка: {e}")
            return []
    
    async def search_collections(self, title: str) -> List[Dict]:
        """Шукаємо колекції за назвою з усіх доступних джерел"""
        print(f"=== ПОШУК КОЛЕКЦІЇ: '{title}' ===")
        
        # Отримуємо всі колекції
        all_collections = await self.get_all_collections()
        
        if not all_collections:
            print("❌ Колекції не знайдено жодним методом")
            return []
        
        # Фільтруємо за назвою (гнучкий пошук)
        filtered = []
        search_title = title.lower().strip()
        
        for collection in all_collections:
            collection_title = collection.get('title', '').lower()
            collection_handle = collection.get('handle', '').lower()
            
            # Шукаємо співпадіння в назві або handle
            if (search_title in collection_title or 
                collection_title in search_title or
                search_title in collection_handle or
                search_title.replace(' ', '-') in collection_handle or
                search_title.replace('-', ' ') in collection_title):
                
                filtered.append(collection)
                print(f"✅ Знайдено: '{collection['title']}' (handle: {collection.get('handle', 'N/A')})")
        
        print(f"=== РЕЗУЛЬТАТ: {len(filtered)} з {len(all_collections)} ===")
        return filtered
    
    async def get_products_by_collection_smart(self, collection_identifier: str, limit: int = 250) -> List[Dict]:
        """Розумне отримання товарів з колекції (по ID, handle або назві)"""
        print(f"=== ОТРИМАННЯ ТОВАРІВ З КОЛЕКЦІЇ: '{collection_identifier}' ===")
        
        # Спочатку пробуємо як handle
        try:
            print("Спроба 1: як handle колекції")
            products = await self.get_products_by_collection_handle(collection_identifier, limit)
            if products:
                print(f"✅ Знайдено {len(products)} товарів через handle")
                return products
        except Exception as e:
            print(f"❌ Handle помилка: {e}")
        
        # Потім як ID (якщо це число)
        try:
            if collection_identifier.isdigit():
                print("Спроба 2: як ID колекції")
                collection_id = int(collection_identifier)
                products = await self.get_products_by_collection(collection_id, limit)
                if products:
                    print(f"✅ Знайдено {len(products)} товарів через ID")
                    return products
        except Exception as e:
            print(f"❌ ID помилка: {e}")
        
        # Нарешті шукаємо колекцію за назвою
        try:
            print("Спроба 3: пошук за назвою")
            collections = await self.search_collections(collection_identifier)
            
            if collections:
                # Беремо першу знайдену колекцію
                collection = collections[0]
                collection_id = collection.get('id')
                collection_handle = collection.get('handle')
                
                print(f"Знайдена колекція: {collection['title']} (ID: {collection_id})")
                
                # Пробуємо отримати товари
                if collection_handle:
                    products = await self.get_products_by_collection_handle(collection_handle, limit)
                    if products:
                        print(f"✅ Знайдено {len(products)} товарів через handle після пошуку")
                        return products
                
                if collection_id:
                    products = await self.get_products_by_collection(collection_id, limit)
                    if products:
                        print(f"✅ Знайдено {len(products)} товарів через ID після пошуку")
                        return products
        except Exception as e:
            print(f"❌ Пошук за назвою помилка: {e}")
        
        print("❌ Товари в колекції не знайдено")
        return []
    
    async def update_variant_price(self, variant_id: int, price: str, compare_at_price: str = None) -> Dict:
        """Оновлюємо ціну варіанту товару"""
        payload = {
            'variant': {
                'id': variant_id,
                'price': price
            }
        }
        
        if compare_at_price:
            payload['variant']['compare_at_price'] = compare_at_price
        
        response = await self._make_request(
            'PUT', f'variants/{variant_id}.json', json=payload
        )
        return response.get('variant', {})
    
    async def get_product_with_variants(self, product_id: int) -> Dict:
        """Отримуємо товар з усіма варіантами"""
        response = await self._make_request('GET', f'products/{product_id}.json')
        return response.get('product', {})