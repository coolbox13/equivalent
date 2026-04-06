#!/usr/bin/env python3
"""
Product Essence Classifier using Anthropic API
For Omfietser supermarket comparison app

This script uses the Anthropic API with automatic rate limiting,
exponential backoff, and a separate product_essences table.
"""

import psycopg2
import asyncio
import aiohttp
import json
import time
import random
from typing import List, Dict, Optional
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('essence_classification.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AnthropicEssenceClassifier:
    def __init__(self, db_config: Dict, anthropic_api_key: str):
        self.db_config = db_config
        self.api_key = anthropic_api_key
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.batch_size = 15  # Conservative for rate limits
        self.min_delay = 1    # Minimum delay between requests
        self.max_delay = 60   # Maximum delay for backoff
        self.max_retries = 5  # Maximum retries on rate limit
        self.model_version = "claude-3-5-sonnet-20241022"
        
        # Rate limiting counters
        self.requests_made = 0
        self.rate_limit_hits = 0
        
    def create_essences_table(self):
        """Create the product_essences table if it doesn't exist"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_essences (
                id SERIAL PRIMARY KEY,
                product_id INTEGER REFERENCES products(id) UNIQUE,
                essence VARCHAR(100),
                confidence DECIMAL(3,2) DEFAULT 0.95,
                created_at TIMESTAMP DEFAULT NOW(),
                model_version VARCHAR(50),
                processing_time_ms INTEGER,
                notes TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_product_essences_product_id 
                ON product_essences(product_id);
            CREATE INDEX IF NOT EXISTS idx_product_essences_essence 
                ON product_essences(essence);
            CREATE INDEX IF NOT EXISTS idx_product_essences_essence_confidence 
                ON product_essences(essence, confidence);
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Product essences table ready")
        
    def get_products_by_category(self, category: str, limit: Optional[int] = None) -> List[Dict]:
        """Fetch unprocessed products from database"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        query = """
        SELECT p.id, p.title, p.main_category, p.brand, p.shop_type, p.current_price
        FROM products p
        LEFT JOIN product_essences pe ON p.id = pe.product_id
        WHERE p.main_category = %s AND pe.product_id IS NULL
        ORDER BY p.id
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, [category])
        columns = [desc[0] for desc in cursor.description]
        products = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        return products
    
    def get_processing_stats(self) -> Dict:
        """Get current processing statistics"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                p.main_category,
                COUNT(*) as total_products,
                COUNT(pe.product_id) as classified,
                COUNT(*) - COUNT(pe.product_id) as remaining,
                AVG(pe.confidence) as avg_confidence,
                AVG(pe.processing_time_ms) as avg_processing_time
            FROM products p
            LEFT JOIN product_essences pe ON p.id = pe.product_id
            GROUP BY p.main_category
            ORDER BY p.main_category
        """)
        
        stats = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return {
            'categories': [
                {
                    'category': row[0],
                    'total': row[1], 
                    'classified': row[2],
                    'remaining': row[3],
                    'avg_confidence': float(row[4]) if row[4] else 0,
                    'avg_processing_time': float(row[5]) if row[5] else 0
                } for row in stats
            ],
            'session_stats': {
                'requests_made': self.requests_made,
                'rate_limit_hits': self.rate_limit_hits
            }
        }
    
    def save_essences_to_db(self, product_essence_pairs: List[tuple], processing_time_ms: int = 0):
        """Save classified essences to separate table"""
        if not product_essence_pairs:
            return
            
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        try:
            for product_id, essence, confidence in product_essence_pairs:
                cursor.execute("""
                    INSERT INTO product_essences (product_id, essence, confidence, model_version, processing_time_ms)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (product_id) DO UPDATE SET
                        essence = EXCLUDED.essence,
                        confidence = EXCLUDED.confidence,
                        created_at = NOW(),
                        model_version = EXCLUDED.model_version,
                        processing_time_ms = EXCLUDED.processing_time_ms
                """, (product_id, essence.strip().lower(), confidence, self.model_version, processing_time_ms))
            
            conn.commit()
            logger.info(f"✅ Saved {len(product_essence_pairs)} essences to database")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Error saving to database: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def create_claude_prompt(self, products: List[Dict], category: str) -> str:
        """Create optimized prompt for Claude API"""
        
        category_guidelines = {
            'Drogisterij': """
Personal care & health products - focus on functional differences:
- Deodorant types: "deodorant spray", "anti-transpirant", "deodorant roller", "deodorant stick"
- Hair care: "shampoo", "conditioner", "haarspray", "haargel", "haarmousse", "droogshampoo"
- Oral care: "tandpasta", "tandenborstel", "mondspoeling", "tandzijde"
- Baby care: "baby shampoo", "baby voeding", "luiers", "luierbroekjes", "babydoekjes"
- Health: "paracetamol", "vitamine d", "hoestdrank", "neusspray"
- Skin care: "dagcrème", "nachtcrème", "bodylotion", "zonnebrand"
""",
            'Zuivel': """
Dairy products - preserve functional differences:
- Milk: "volle melk", "halfvolle melk", "magere melk", "karnemelk"
- Yogurt: "yoghurt naturel", "griekse yoghurt", "kwark", "skyr", "vla"
- Cheese: "jonge kaas", "oude kaas", "belegen kaas", "geitenkaas", "mozzarella"
- Butter: "boter", "halvarine", "margarine"
""",
            'Vlees': """
Meat products - specify type and preparation:
- Meat type + preparation: "rund gehakt", "varken gehakt", "kip filet", "rund biefstuk"
- Processed: "gekookte ham", "rauwe ham", "salami", "worst", "spek"
- Fish: "zalm filet", "tonijn", "garnalen"
""",
            'Brood & Gebak': """
Bread & baked goods - include key characteristics:
- Bread: "volkoren brood", "wit brood", "meergranen brood", "casino brood"
- Special: "glutenvrij brood", "zuurdesem brood"
- Pastry: "croissant", "cake", "koekjes", "taart", "muffin"
"""
        }
        
        guidelines = category_guidelines.get(category, category_guidelines['Drogisterij'])
        
        return f"""Extract product essence from Dutch {category} products. Follow these rules exactly:

RULES:
1. Remove ALL brand names (AH, Jumbo, PLUS, ALDI, NIVEA, Dove, Andrélon, Pampers, etc.)
2. Remove quantities/packaging (ml, kg, gram, stuks, pak, fles, 300ml, 1L, 2-pack, etc.)
3. Remove marketing terms (biologisch, premium, extra, vers, ultra, advanced, perfect, excellent)
4. Keep ONLY core product type and essential functional differences
5. Use lowercase, 1-3 words maximum
6. Handle Dutch compounds correctly (anti-transpirant, halfvolle melk)

{guidelines}

EXAMPLES:
"NIVEA Dry Comfort Anti-Transpirant 50 ml" → "anti-transpirant"
"AH Biologische Halfvolle Melk 1L" → "halfvolle melk"
"Pampers Baby-Dry Pants Maat 6, 64 Luierbroekjes" → "luierbroekjes"

Products to classify:
{chr(10).join(f"{i}. {p['title']}" for i, p in enumerate(products, 1))}

Return exactly {len(products)} essences, one per line, no numbers or explanations:"""

    def parse_claude_response(self, response: str, expected_count: int) -> List[str]:
        """Parse Claude's response into clean essences with quality scoring"""
        lines = response.strip().split('\n')
        essences = []
        
        for line in lines:
            # Clean up the line
            cleaned = line.strip().lower()
            # Remove leading numbers, dots, dashes
            cleaned = cleaned.lstrip('0123456789. -').strip()
            
            if cleaned and len(cleaned.split()) <= 4:  # Reasonable essence
                essences.append(cleaned)
        
        # Validate count and log issues
        if len(essences) != expected_count:
            logger.warning(f"Expected {expected_count} essences, got {len(essences)}")
            logger.debug(f"Raw response: {response[:200]}...")
            
            # Pad with 'unknown' if needed
            while len(essences) < expected_count:
                essences.append('unknown')
            essences = essences[:expected_count]
        
        return essences
    
    def calculate_confidence_score(self, essences: List[str], products: List[Dict]) -> List[float]:
        """Calculate confidence scores based on essence quality"""
        scores = []
        
        for essence, product in zip(essences, products):
            score = 0.95  # Base confidence
            
            # Reduce confidence for issues
            if essence == 'unknown':
                score = 0.3
            elif len(essence.split()) > 3:
                score -= 0.1  # Too long
            elif any(brand.lower() in essence for brand in ['nivea', 'dove', 'ah', 'jumbo']):
                score -= 0.2  # Brand leaked through
            elif any(term in essence for term in ['ml', 'kg', 'gram', 'pack']):
                score -= 0.15  # Quantity leaked through
            elif len(essence) < 3:
                score -= 0.1  # Too short
            
            scores.append(max(0.1, score))  # Minimum confidence of 0.1
        
        return scores
    
    async def handle_rate_limit(self, attempt: int, response_headers: dict = None):
        """Handle rate limiting with exponential backoff"""
        self.rate_limit_hits += 1
        
        # Extract rate limit info from headers if available
        reset_time = None
        if response_headers:
            reset_time = response_headers.get('x-ratelimit-reset-time')
        
        if reset_time:
            try:
                wait_time = max(1, int(reset_time) - int(time.time()))
                logger.warning(f"Rate limited. Waiting {wait_time}s until reset...")
                await asyncio.sleep(wait_time)
                return
            except (ValueError, TypeError):
                pass
        
        # Fallback to exponential backoff
        delay = min(self.min_delay * (2 ** attempt) + random.uniform(0, 2), self.max_delay)
        logger.warning(f"Rate limited. Backing off for {delay:.1f}s (attempt {attempt + 1})")
        await asyncio.sleep(delay)
    
    async def classify_batch_with_retry(self, products: List[Dict], category: str) -> tuple:
        """Classify a batch with automatic retry and rate limiting"""
        prompt = self.create_claude_prompt(products, category)
        
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()
                
                headers = {
                    "x-api-key": self.api_key,
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01"
                }
                
                data = {
                    "model": self.model_version,
                    "max_tokens": 1000,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}]
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.api_url, headers=headers, json=data) as response:
                        self.requests_made += 1
                        processing_time = int((time.time() - start_time) * 1000)
                        
                        if response.status == 429:
                            # Rate limited
                            await self.handle_rate_limit(attempt, dict(response.headers))
                            continue
                        elif response.status == 400:
                            # Bad request - likely prompt too long
                            logger.error(f"Bad request (400) - prompt may be too long")
                            return ['unknown'] * len(products), [0.3] * len(products), processing_time
                        elif response.status != 200:
                            # Other error
                            error_text = await response.text()
                            logger.error(f"API error {response.status}: {error_text}")
                            if attempt == self.max_retries - 1:
                                return ['unknown'] * len(products), [0.3] * len(products), processing_time
                            await asyncio.sleep(2 ** attempt)
                            continue
                        
                        result = await response.json()
                        response_text = result['content'][0]['text']
                        
                        # Parse and validate response
                        essences = self.parse_claude_response(response_text, len(products))
                        confidence_scores = self.calculate_confidence_score(essences, products)
                        
                        logger.info(f"✅ Classified {len(products)} products in {processing_time}ms")
                        return essences, confidence_scores, processing_time
            
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Unexpected error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        
        # All retries failed
        logger.error(f"All retries failed for batch of {len(products)} products")
        return ['unknown'] * len(products), [0.3] * len(products), 0
    
    async def process_category(self, category: str, max_products: Optional[int] = None, preview_only: bool = False):
        """Process entire category with progress tracking"""
        logger.info(f"🚀 Processing category: {category}")
        
        # Ensure essences table exists
        self.create_essences_table()
        
        # Get products to process
        products = self.get_products_by_category(category, max_products)
        
        if not products:
            logger.info(f"✅ No unprocessed products found in {category}")
            return 0
        
        logger.info(f"📊 Found {len(products)} products to process")
        
        if preview_only:
            logger.info("👀 PREVIEW MODE - showing first batch only")
            products = products[:self.batch_size]
        
        # Process in batches
        total_processed = 0
        
        for i in range(0, len(products), self.batch_size):
            batch = products[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (len(products) + self.batch_size - 1) // self.batch_size
            
            logger.info(f"🔄 Processing batch {batch_num}/{total_batches} ({len(batch)} products)")
            
            # Classify the batch
            essences, confidence_scores, processing_time = await self.classify_batch_with_retry(batch, category)
            
            # Show results
            print(f"\n📋 BATCH {batch_num} RESULTS:")
            print(f"{'TITLE':<50} {'ESSENCE':<20} {'CONF':<5} {'SHOP':<8} {'PRICE'}")
            print("-" * 90)
            
            results = []
            avg_confidence = sum(confidence_scores) / len(confidence_scores)
            
            for product, essence, confidence in zip(batch, essences, confidence_scores):
                title = product['title'][:47] + "..." if len(product['title']) > 50 else product['title']
                print(f"{title:<50} {essence:<20} {confidence:.2f} {product['shop_type']:<8} €{product['current_price']}")
                results.append((product['id'], essence, confidence))
            
            print(f"Batch stats: Avg confidence: {avg_confidence:.2f}, Processing time: {processing_time}ms")
            
            if not preview_only:
                # Save to database
                self.save_essences_to_db(results, processing_time)
                total_processed += len(batch)
                
                # Brief delay between batches
                if i + self.batch_size < len(products):
                    await asyncio.sleep(self.min_delay)
            else:
                print(f"\n👀 Preview complete - {len(batch)} products shown")
                break
        
        if not preview_only:
            logger.info(f"🎉 Completed! Processed {total_processed} products in {category}")
            logger.info(f"📊 Session stats: {self.requests_made} requests, {self.rate_limit_hits} rate limits")
        
        return total_processed if not preview_only else 0

# CLI Interface
async def main():
    print("🛒 OMFIETSER ESSENCE CLASSIFIER (Anthropic API Version)")
    print("="*65)
    
    # Configuration
    db_config = {
        'host': 'localhost',
        'database': 'your_db_name',  # UPDATE THIS
        'user': 'your_username',     # UPDATE THIS
        'password': 'your_password'  # UPDATE THIS
    }
    
    # Get API key
    import os
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        api_key = input("🔑 Enter your Anthropic API key: ").strip()
        if not api_key:
            print("❌ API key required")
            return
    
    try:
        classifier = AnthropicEssenceClassifier(db_config, api_key)
        
        # Interactive menu
        while True:
            # Show current status
            stats = classifier.get_processing_stats()
            
            print(f"\n📊 PROCESSING STATUS:")
            print(f"{'CATEGORY':<20} {'TOTAL':<8} {'DONE':<8} {'LEFT':<8} {'%':<8} {'CONF':<6}")
            print("-" * 70)
            for cat_stats in stats['categories']:
                pct = (cat_stats['classified'] / cat_stats['total'] * 100) if cat_stats['total'] > 0 else 0
                conf = cat_stats['avg_confidence']
                print(f"{cat_stats['category']:<20} {cat_stats['total']:<8} {cat_stats['classified']:<8} {cat_stats['remaining']:<8} {pct:.1f}% {conf:.2f}")
            
            session_stats = stats['session_stats']
            print(f"\nSession: {session_stats['requests_made']} requests, {session_stats['rate_limit_hits']} rate limits")
            
            print(f"\n{'='*50}")
            print("📋 CLASSIFICATION MENU")
            print("="*50)
            print("1. Preview classification (first 15 products)")
            print("2. Process category (all remaining products)")
            print("3. Process category (limited number)")
            print("4. Exit")
            
            choice = input("\nSelect option (1-4): ").strip()
            
            if choice == '1':
                category = input("📂 Category to preview: ").strip()
                if category:
                    await classifier.process_category(category, max_products=15, preview_only=True)
                    
            elif choice == '2':
                category = input("📂 Category to process (all products): ").strip()
                if category:
                    processed = await classifier.process_category(category)
                    print(f"\n✅ Session complete: {processed} products processed")
                    
            elif choice == '3':
                category = input("📂 Category to process: ").strip()
                try:
                    limit = int(input("🔢 Max products to process: "))
                    if category and limit > 0:
                        processed = await classifier.process_category(category, max_products=limit)
                        print(f"\n✅ Session complete: {processed} products processed")
                except ValueError:
                    print("❌ Please enter a valid number")
                    
            elif choice == '4':
                print("👋 Goodbye!")
                break
            else:
                print("❌ Invalid choice")
                
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
