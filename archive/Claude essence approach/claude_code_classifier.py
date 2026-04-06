#!/usr/bin/env python3
"""
Product Essence Classifier using Claude Code (MCP)
For Omfietser supermarket comparison app

This script uses a separate product_essences table to avoid interfering 
with main product queries and includes proper rate limiting handling.
"""

import psycopg2
import json
import time
import random
from typing import List, Dict, Optional
from datetime import datetime

class ClaudeCodeEssenceClassifier:
    def __init__(self, db_config: Dict):
        self.db_config = db_config
        self.batch_size = 25  # Conservative for rate limits
        self.min_delay = 1    # Minimum delay between batches
        self.max_delay = 5    # Maximum delay for backoff
        self.max_retries = 3  # Maximum retries on failure
        self.model_version = "claude-3.5-sonnet-manual"  # Track which model was used
        
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
        print("✅ Product essences table ready")
        
    def get_products_by_category(self, category: str, limit: Optional[int] = None, offset: int = 0) -> List[Dict]:
        """Fetch products that don't have essences yet"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        query = """
        SELECT p.id, p.title, p.main_category, p.brand, p.shop_type, p.current_price
        FROM products p
        LEFT JOIN product_essences pe ON p.id = pe.product_id
        WHERE p.main_category = %s AND pe.product_id IS NULL
        ORDER BY p.id
        """
        
        params = [category]
        if limit:
            query += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])
        
        cursor.execute(query, params)
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
                COUNT(*) - COUNT(pe.product_id) as remaining
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
                    'remaining': row[3]
                } for row in stats
            ]
        }
    
    def save_essences_to_db(self, product_essence_pairs: List[tuple], confidence: float = 0.95):
        """Save classified essences to separate table"""
        if not product_essence_pairs:
            return
            
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        try:
            for product_id, essence in product_essence_pairs:
                cursor.execute("""
                    INSERT INTO product_essences (product_id, essence, confidence, model_version)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (product_id) DO UPDATE SET
                        essence = EXCLUDED.essence,
                        confidence = EXCLUDED.confidence,
                        created_at = NOW(),
                        model_version = EXCLUDED.model_version
                """, (product_id, essence.strip().lower(), confidence, self.model_version))
            
            conn.commit()
            print(f"✅ Saved {len(product_essence_pairs)} essences to database")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ Error saving to database: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def create_claude_prompt(self, products: List[Dict], category: str) -> str:
        """Create the prompt for Claude to classify essences"""
        
        category_instructions = {
            'Drogisterij': """
Focus on personal care and health products:
- Personal care: deodorant, shampoo, tandpasta, crème, zeep
- Baby products: baby + core function (baby voeding, baby shampoo, luiers)
- Health: vitamins, pain relief, supplements (paracetamol, vitamine d)
- Beauty: make-up, hair styling products
- Oral care: tandenborstel, mondspoeling, tandzijde
""",
            'Zuivel': """
Focus on dairy products:
- Milk: include fat content (volle melk, halfvolle melk, magere melk)
- Yogurt: include type (griekse yoghurt, yoghurt naturel, kwark, skyr)
- Cheese: include age when important (jonge kaas, oude kaas, belegen kaas)
- Butter: boter, halvarine, margarine
""",
            'Vlees': """
Focus on meat products:
- Type of meat: rund, varken, kip, lam, vis
- Preparation: gehakt, filet, worst, ham, spek
- Keep preparation method when defining: gekookte ham vs rauwe ham
""",
            'Brood & Gebak': """
Focus on bread and baked goods:
- Bread type: volkoren brood, wit brood, casino brood, meergranen brood
- Pastry type: croissant, koek, cake, taart
- Include key characteristics: zuurdesem, glutenvrij
"""
        }
        
        instructions = category_instructions.get(category, category_instructions['Drogisterij'])
        
        prompt = f"""Extract product "essence" from these Dutch {category} products.

RULES:
1. Remove ALL brand names (AH, Jumbo, PLUS, ALDI, NIVEA, Dove, Andrélon, etc.)
2. Remove quantities, weights, packaging (ml, kg, gram, stuks, pak, fles, 300ml, 1L, etc.)
3. Remove marketing terms (biologisch, premium, extra, vers, ultra, advanced, perfect)
4. Keep core product identity and functional differences only
5. Use lowercase, typically 1-3 words maximum
6. Handle Dutch compounds properly (anti-transpirant stays together)

{instructions}

EXAMPLES for {category}:
- "NIVEA Dry Comfort Anti-Transpirant 50 ml" → "anti-transpirant"
- "Andrélon Special oil & care shampoo 300ml" → "shampoo" 
- "Pampers Baby-Dry Pants Maat 6, 64 Luierbroekjes" → "luierbroekjes"
- "AH Biologische Halfvolle Melk 1L" → "halfvolle melk"
- "Libresse Ultra regular+ wing maandverband" → "maandverband"

Now classify these {len(products)} products:

"""
        
        for i, product in enumerate(products, 1):
            prompt += f"{i}. {product['title']}\n"
        
        prompt += f"""
Return exactly {len(products)} essences, one per line, no numbering or explanations:"""
        
        return prompt
    
    def parse_claude_response(self, response: str, expected_count: int) -> List[str]:
        """Parse Claude's response into list of essences with validation"""
        lines = [line.strip().lower() for line in response.strip().split('\n') if line.strip()]
        
        # Filter out any numbered lines or explanatory text
        essences = []
        for line in lines:
            # Remove leading numbers and dots
            cleaned = line.lstrip('0123456789. -').strip()
            if cleaned and len(cleaned.split()) <= 4:  # Reasonable essence length
                essences.append(cleaned)
        
        # Ensure we have the right count
        if len(essences) != expected_count:
            print(f"⚠️  Warning: Expected {expected_count} essences, got {len(essences)}")
            print(f"Raw response: {response[:200]}...")
            
            # Pad with 'unknown' if needed
            while len(essences) < expected_count:
                essences.append('unknown')
            essences = essences[:expected_count]
        
        return essences
    
    def handle_processing_delay(self, attempt: int = 0):
        """Handle delays with exponential backoff for rate limiting"""
        if attempt == 0:
            # Normal delay between batches
            delay = self.min_delay + random.uniform(0, 1)
        else:
            # Exponential backoff for retries
            delay = min(self.min_delay * (2 ** attempt) + random.uniform(0, 2), self.max_delay)
        
        print(f"⏳ Waiting {delay:.1f} seconds...")
        time.sleep(delay)
    
    def process_category_interactive(self, category: str, max_products: Optional[int] = None):
        """Process entire category using interactive Claude Code workflow"""
        print(f"🚀 Processing category: {category}")
        print(f"📋 Model: {self.model_version}")
        
        # Ensure essences table exists
        self.create_essences_table()
        
        # Get products to process
        products = self.get_products_by_category(category, max_products)
        
        if not products:
            print(f"✅ No unprocessed products found in {category}")
            return 0
        
        print(f"📊 Found {len(products)} products to process")
        
        # Process in batches
        processed = 0
        batch_num = 0
        
        for i in range(0, len(products), self.batch_size):
            batch = products[i:i + self.batch_size]
            batch_num += 1
            total_batches = (len(products) + self.batch_size - 1) // self.batch_size
            
            print(f"\n🔄 Processing batch {batch_num}/{total_batches} ({len(batch)} products)")
            
            # Create prompt for Claude
            prompt = self.create_claude_prompt(batch, category)
            
            # Retry logic for this batch
            for attempt in range(self.max_retries):
                try:
                    print("=" * 80)
                    print(f"📤 CLAUDE PROMPT (Batch {batch_num}, Attempt {attempt + 1}):")
                    print("=" * 80)
                    print(prompt)
                    print("=" * 80)
                    
                    print(f"\n🤖 Send the above prompt to Claude and paste the response below:")
                    print("💡 Tip: Copy the entire prompt, send to Claude, then paste response here")
                    print("⌨️  Paste Claude's response (press Enter twice when done):")
                    
                    # Collect multi-line response
                    response_lines = []
                    empty_line_count = 0
                    
                    while True:
                        line = input()
                        if line.strip() == "":
                            empty_line_count += 1
                            if empty_line_count >= 2:  # Two empty lines = done
                                break
                        else:
                            empty_line_count = 0
                            response_lines.append(line)
                    
                    claude_response = '\n'.join(response_lines).strip()
                    
                    if not claude_response:
                        print("❌ Empty response received. Please try again.")
                        continue
                    
                    # Parse response
                    essences = self.parse_claude_response(claude_response, len(batch))
                    
                    # Show results for review
                    print(f"\n📋 BATCH {batch_num} CLASSIFICATION RESULTS:")
                    print(f"{'TITLE':<55} {'ESSENCE':<20} {'SHOP':<8} {'PRICE'}")
                    print("-" * 90)
                    
                    for product, essence in zip(batch, essences):
                        title = product['title'][:52] + "..." if len(product['title']) > 55 else product['title']
                        print(f"{title:<55} {essence:<20} {product['shop_type']:<8} €{product['current_price']}")
                    
                    # Quality check
                    print(f"\n🔍 Quality check:")
                    print(f"   - Expected {len(batch)} essences, got {len(essences)}")
                    print(f"   - Average essence length: {sum(len(e.split()) for e in essences) / len(essences):.1f} words")
                    
                    unknown_count = sum(1 for e in essences if e == 'unknown')
                    if unknown_count > 0:
                        print(f"   ⚠️  {unknown_count} products got 'unknown' essence")
                    
                    # Confirm before saving
                    while True:
                        save_confirm = input(f"\n💾 Save these {len(batch)} essences to database? (y/n/retry): ").lower().strip()
                        if save_confirm in ['y', 'yes']:
                            # Save to database
                            product_essence_pairs = [(p['id'], e) for p, e in zip(batch, essences)]
                            self.save_essences_to_db(product_essence_pairs)
                            processed += len(batch)
                            break
                        elif save_confirm in ['n', 'no']:
                            print("❌ Skipping this batch")
                            break
                        elif save_confirm in ['r', 'retry']:
                            print("🔄 Retrying this batch...")
                            break
                        else:
                            print("Please enter 'y', 'n', or 'retry'")
                    
                    if save_confirm in ['y', 'yes']:
                        break  # Success, move to next batch
                    elif save_confirm in ['n', 'no']:
                        break  # Skip, move to next batch
                    # If retry, continue the attempt loop
                    
                except KeyboardInterrupt:
                    print(f"\n⏹️  Processing interrupted by user")
                    return processed
                except Exception as e:
                    print(f"❌ Error in batch {batch_num}, attempt {attempt + 1}: {e}")
                    if attempt < self.max_retries - 1:
                        print(f"🔄 Retrying in a moment...")
                        self.handle_processing_delay(attempt + 1)
                    else:
                        print(f"❌ Max retries reached for batch {batch_num}, skipping...")
                        break
            
            # Delay before next batch (if there is one)
            if i + self.batch_size < len(products):
                self.handle_processing_delay()
        
        print(f"\n🎉 Processing complete!")
        print(f"📊 Processed {processed} out of {len(products)} products in {category}")
        
        return processed

# Main execution
if __name__ == "__main__":
    print("🛒 OMFIETSER ESSENCE CLASSIFIER (Claude Code Version)")
    print("="*60)
    
    # Database configuration - UPDATE THESE VALUES
    db_config = {
        'host': 'localhost',
        'database': 'your_db_name',  # UPDATE THIS
        'user': 'your_username',     # UPDATE THIS
        'password': 'your_password'  # UPDATE THIS
    }
    
    print("⚙️  Database config:")
    print(f"   Host: {db_config['host']}")
    print(f"   Database: {db_config['database']}")
    print(f"   User: {db_config['user']}")
    
    try:
        classifier = ClaudeCodeEssenceClassifier(db_config)
        
        # Show current status
        print("\n📊 Current processing status:")
        stats = classifier.get_processing_stats()
        
        print(f"{'CATEGORY':<20} {'TOTAL':<8} {'DONE':<8} {'REMAINING':<10} {'%':<8}")
        print("-" * 60)
        for cat_stats in stats['categories']:
            pct = (cat_stats['classified'] / cat_stats['total'] * 100) if cat_stats['total'] > 0 else 0
            print(f"{cat_stats['category']:<20} {cat_stats['total']:<8} {cat_stats['classified']:<8} {cat_stats['remaining']:<10} {pct:.1f}%")
        
        # Interactive menu
        while True:
            print(f"\n{'='*50}")
            print("📋 CLASSIFICATION MENU")
            print("="*50)
            print("1. Process category (all remaining products)")
            print("2. Process category (limited number)")
            print("3. Show processing status")
            print("4. Exit")
            
            choice = input("\nSelect option (1-4): ").strip()
            
            if choice == '1':
                category = input("📂 Category to process: ").strip()
                if category:
                    processed = classifier.process_category_interactive(category)
                    print(f"\n✅ Session complete: {processed} products processed")
                
            elif choice == '2':
                category = input("📂 Category to process: ").strip()
                try:
                    limit = int(input("🔢 Max products to process: "))
                    if category and limit > 0:
                        processed = classifier.process_category_interactive(category, limit)
                        print(f"\n✅ Session complete: {processed} products processed")
                except ValueError:
                    print("❌ Please enter a valid number")
                
            elif choice == '3':
                stats = classifier.get_processing_stats()
                print(f"\n📊 PROCESSING STATUS:")
                print(f"{'CATEGORY':<20} {'TOTAL':<8} {'DONE':<8} {'REMAINING':<10} {'%':<8}")
                print("-" * 60)
                for cat_stats in stats['categories']:
                    pct = (cat_stats['classified'] / cat_stats['total'] * 100) if cat_stats['total'] > 0 else 0
                    print(f"{cat_stats['category']:<20} {cat_stats['total']:<8} {cat_stats['classified']:<8} {cat_stats['remaining']:<10} {pct:.1f}%")
                
            elif choice == '4':
                print("👋 Goodbye!")
                break
            else:
                print("❌ Invalid choice")
                
    except psycopg2.Error as e:
        print(f"❌ Database connection error: {e}")
        print("💡 Please check your database configuration in the script")
    except KeyboardInterrupt:
        print(f"\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
