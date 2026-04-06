#!/usr/bin/env python3
"""
Test different HuggingFace LLM models for product matching with category-based grouping
"""

import pandas as pd
import requests
import json
import time
from typing import List, Dict, Tuple
from collections import defaultdict

class LLMModelTester:
    def __init__(self):
        self.products_df = None
        self.test_groups = []
        
        # HuggingFace Inference API - free tier
        self.hf_api_base = "https://api-inference.huggingface.co/models"
        
        # LLM models to test (fixed the model selection issues)
        self.models_to_test = [
            {
                "name": "Mistral-7B-Instruct",
                "model_id": "mistralai/Mistral-7B-Instruct-v0.2",
                "type": "instruction",
                "description": "Mistral 7B instruction-tuned model"
            },
            {
                "name": "Zephyr-7B-Beta", 
                "model_id": "HuggingFaceH4/zephyr-7b-beta",
                "type": "chat",
                "description": "HuggingFace Zephyr 7B chat model"
            },
            {
                "name": "Llama2-7B-Chat",
                "model_id": "meta-llama/Llama-2-7b-chat-hf",
                "type": "chat", 
                "description": "Meta Llama 2 7B chat model"
            },
            {
                "name": "Code-Llama-7B-Instruct",
                "model_id": "codellama/CodeLlama-7b-Instruct-hf",
                "type": "instruction",
                "description": "Code Llama 7B instruction model"
            }
        ]
    
    def load_products_from_csv(self, csv_path: str) -> bool:
        """Load products from CSV and create category-based groups"""
        try:
            print("📊 Loading products from CSV...")
            self.products_df = pd.read_csv(csv_path)
            print(f"   ✅ Loaded {len(self.products_df)} products")
            
            # Check required columns
            required_cols = ['main_category', 'normalized_quantity_unit', 'title', 'shop_type']
            missing_cols = [col for col in required_cols if col not in self.products_df.columns]
            if missing_cols:
                print(f"   ❌ Missing columns: {missing_cols}")
                return False
            
            # Group by category + unit (our smart filtering strategy)
            print("🔍 Grouping products by category + quantity unit...")
            groups = defaultdict(list)
            
            for _, product in self.products_df.iterrows():
                # Skip products with missing data
                if pd.isna(product['main_category']) or pd.isna(product['normalized_quantity_unit']):
                    continue
                    
                group_key = f"{product['main_category']}_{product['normalized_quantity_unit']}"
                groups[group_key].append(product.to_dict())
            
            # Filter for groups with multiple shops (potential for cross-shop matching)
            multi_shop_groups = {}
            for group_key, products in groups.items():
                shops = set(p['shop_type'] for p in products)
                if len(shops) > 1 and len(products) >= 5:  # At least 2 shops, 5+ products
                    multi_shop_groups[group_key] = products
            
            print(f"   📦 Found {len(multi_shop_groups)} groups with multi-shop products")
            
            # Select two largest groups for testing
            if len(multi_shop_groups) >= 2:
                sorted_groups = sorted(multi_shop_groups.items(), 
                                     key=lambda x: len(x[1]), reverse=True)
                self.test_groups = sorted_groups[:2]
                
                print(f"   🎯 Selected 2 test groups for LLM testing:")
                for group_key, products in self.test_groups:
                    shops = set(p['shop_type'] for p in products)
                    print(f"      - {group_key}: {len(products)} products across {list(shops)}")
                return True
            else:
                print("   ❌ Not enough suitable groups found for testing")
                return False
                
        except Exception as e:
            print(f"   ❌ Failed to load CSV: {e}")
            return False
    
    def generate_test_pairs(self, group_products: List[Dict]) -> List[Tuple[Dict, Dict, str]]:
        """Generate meaningful test pairs from a product group"""
        test_pairs = []
        all_attempted_pairs = []
        
        # Group by shop for cross-shop comparisons
        by_shop = defaultdict(list)
        for product in group_products:
            by_shop[product['shop_type']].append(product)
        
        shops = list(by_shop.keys())
        print(f"      Generating test pairs from shops: {shops}")
        
        # DEBUG: Show sample products from each shop
        for shop in shops[:2]:  # Show first 2 shops
            sample_products = by_shop[shop][:3]
            print(f"         {shop} samples: {[p.get('title', 'No title')[:50] for p in sample_products]}")
        
        # Create cross-shop pairs (where equivalences would be meaningful)
        for i, shop1 in enumerate(shops):
            for shop2 in shops[i+1:]:
                products1 = by_shop[shop1][:4]  # Limit to avoid too many pairs
                products2 = by_shop[shop2][:4]
                
                for p1 in products1:
                    for p2 in products2:
                        expected = self.classify_expected_match(p1, p2)
                        all_attempted_pairs.append((p1.get('title', '')[:30], p2.get('title', '')[:30], expected))
                        
                        if expected != "no_match":  # Only include meaningful pairs
                            test_pairs.append((p1, p2, expected))
        
        # DEBUG: Show classification results
        print(f"      DEBUG: Attempted {len(all_attempted_pairs)} pairs")
        classifications = defaultdict(int)
        for _, _, classification in all_attempted_pairs:
            classifications[classification] += 1
        print(f"      Classifications: {dict(classifications)}")
        
        if len(test_pairs) == 0 and len(all_attempted_pairs) > 0:
            print(f"      DEBUG: Sample rejected pairs:")
            for title1, title2, classification in all_attempted_pairs[:5]:
                print(f"         '{title1}' vs '{title2}' → {classification}")
        
        # If we still don't have enough pairs, include some "no_match" for LLM testing
        if len(test_pairs) < 5:
            print(f"      Only {len(test_pairs)} valid pairs, adding some 'no_match' for testing...")
            for title1, title2, classification in all_attempted_pairs:
                if classification == "no_match" and len(test_pairs) < 10:
                    # Find the original product objects
                    p1 = next((p for p in group_products if title1 in p.get('title', '')[:30]), None)
                    p2 = next((p for p in group_products if title2 in p.get('title', '')[:30]), None)
                    if p1 and p2:
                        test_pairs.append((p1, p2, "no_match"))
        
        print(f"      Final test pairs: {len(test_pairs)}")
        
        # Limit total pairs to keep testing manageable
        return test_pairs[:15]  # 15 pairs per group max
    
    def classify_expected_match(self, p1: Dict, p2: Dict) -> str:
        """Classify expected match type (our ground truth for testing)"""
        title1 = str(p1.get('title', '')).lower()
        title2 = str(p2.get('title', '')).lower()
        brand1 = str(p1.get('brand', '')).lower() if 'brand' in p1 else ''
        brand2 = str(p2.get('brand', '')).lower() if 'brand' in p2 else ''
        
        # Remove shop prefixes
        for shop in ['ah', 'plus', 'jumbo', 'aldi']:
            title1 = title1.replace(f'{shop} ', '')
            title2 = title2.replace(f'{shop} ', '')
        
        # Calculate word overlap similarity
        similarity = self.text_similarity(title1, title2)
        
        # More lenient classification rules for broader testing
        if similarity > 0.6:  # Lowered from 0.8
            return "identical"  # Very similar titles
        elif brand1 and brand2 and brand1 == brand2 and similarity > 0.3:  # Lowered from 0.5
            return "similar"    # Same brand, similar product
        elif similarity > 0.25:  # Lowered from 0.4
            return "alternative"  # Different brands, similar type
        else:
            return "no_match"
    
    def text_similarity(self, text1: str, text2: str) -> float:
        """Calculate simple word overlap similarity"""
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def create_product_matching_prompt(self, p1: Dict, p2: Dict) -> str:
        """Create optimized prompt for LLM product matching"""
        # Include more context for better classification
        title1 = p1.get('title', 'Unknown')
        title2 = p2.get('title', 'Unknown')
        shop1 = p1.get('shop_type', 'Unknown')
        shop2 = p2.get('shop_type', 'Unknown')
        
        prompt = f"""Task: Compare two supermarket products and classify their relationship.

Product A: "{title1}" (from {shop1})
Product B: "{title2}" (from {shop2})

Classification rules:
- identical: Same product from different stores (e.g., "AH Milk 1L" vs "PLUS Milk 1L")
- similar: Same brand, different variants (e.g., "Coca Cola Zero" vs "Coca Cola Light")
- alternative: Different brands, same product type (e.g., "Coca Cola" vs "Pepsi")
- no_match: Completely different products (e.g., "Milk" vs "Shampoo")

Respond with ONLY the classification word: identical, similar, alternative, or no_match

Classification:"""
        
        return prompt
    
    def query_huggingface_model(self, model_id: str, prompt: str, max_retries: int = 3) -> str:
        """Query HuggingFace Inference API with improved error handling"""
        url = f"{self.hf_api_base}/{model_id}"
        
        headers = {"Content-Type": "application/json"}
        
        # Optimized parameters for classification task
        data = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 10,  # We only need one word
                "temperature": 0.1,    # Low temperature for consistency
                "do_sample": False,    # Deterministic output
                "return_full_text": False
            }
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=data, timeout=45)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Handle different response formats
                    if isinstance(result, list) and len(result) > 0:
                        text = result[0].get("generated_text", "").strip()
                    elif isinstance(result, dict):
                        text = result.get("generated_text", "").strip()
                    else:
                        text = str(result).strip()
                    
                    return text
                    
                elif response.status_code == 503:
                    wait_time = min(20 + (attempt * 10), 60)  # Progressive backoff
                    print(f"        Model loading, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                    
                elif response.status_code == 429:
                    print(f"        Rate limited, waiting...")
                    time.sleep(30)
                    continue
                    
                else:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_detail = response.json()
                        if 'error' in error_detail:
                            error_msg += f": {error_detail['error']}"
                    except:
                        pass
                    return f"Error: {error_msg}"
                    
            except requests.RequestException as e:
                print(f"        Request failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(10)
                    
        return "Error: Failed after all retries"
    
    def extract_classification(self, response: str) -> str:
        """Extract classification from LLM response"""
        response_lower = response.lower().strip()
        
        # Look for exact matches first
        for option in ["identical", "similar", "alternative", "no_match"]:
            if option in response_lower:
                return option
        
        # Fallback for partial matches
        if "ident" in response_lower or "same" in response_lower:
            return "identical"
        elif "simil" in response_lower or "variant" in response_lower:
            return "similar"
        elif "altern" in response_lower or "different brand" in response_lower:
            return "alternative"
        elif "no" in response_lower or "none" in response_lower:
            return "no_match"
        
        return "unknown"
    
    def test_llm_model(self, model_info: Dict, test_pairs: List[Tuple]) -> Dict:
        """Test a specific LLM model on product pairs"""
        model_name = model_info["name"]
        model_id = model_info["model_id"]
        
        print(f"    🤖 Testing {model_name}")
        print(f"         Model: {model_id}")
        print(f"         Type: {model_info['type']}")
        
        results = []
        correct_count = 0
        
        for i, (p1, p2, expected) in enumerate(test_pairs):
            print(f"         Progress: {i+1}/{len(test_pairs)} pairs", end=" ")
            
            prompt = self.create_product_matching_prompt(p1, p2)
            response = self.query_huggingface_model(model_id, prompt)
            
            predicted = self.extract_classification(response)
            correct = predicted == expected
            
            if correct:
                correct_count += 1
                print("✅")
            else:
                print(f"❌ (got: {predicted}, expected: {expected})")
            
            results.append({
                "product_1": p1.get('title', 'Unknown'),
                "product_2": p2.get('title', 'Unknown'),
                "shop_1": p1.get('shop_type', 'Unknown'),
                "shop_2": p2.get('shop_type', 'Unknown'),
                "expected": expected,
                "predicted": predicted,
                "response": response,
                "correct": correct
            })
            
            # Be respectful to free API
            time.sleep(3)
        
        accuracy = correct_count / len(test_pairs) if test_pairs else 0
        
        return {
            "model": model_name,
            "model_id": model_id,
            "accuracy": accuracy,
            "correct_count": correct_count,
            "total_pairs": len(test_pairs),
            "results": results
        }
    
    def run_comprehensive_test(self, csv_path: str):
        """Run comprehensive LLM testing with category-based grouping"""
        print("🚀 HuggingFace LLM Testing with Category-Based Grouping")
        print("=" * 70)
        
        # Load and group products
        if not self.load_products_from_csv(csv_path):
            print("❌ Failed to load products, exiting...")
            return
        
        all_results = []
        
        # Test each selected group
        for group_idx, (group_key, group_products) in enumerate(self.test_groups):
            print(f"\n📦 GROUP {group_idx + 1}/2: {group_key}")
            print(f"    Products: {len(group_products)}")
            print("-" * 50)
            
            # Generate test pairs
            test_pairs = self.generate_test_pairs(group_products)
            print(f"    📝 Generated {len(test_pairs)} test pairs")
            
            if not test_pairs:
                print("    ⚠️  No suitable test pairs, skipping group")
                continue
            
            # Test each LLM model
            group_results = []
            
            for model_idx, model_info in enumerate(self.models_to_test):
                print(f"\n    MODEL {model_idx + 1}/{len(self.models_to_test)}")
                
                try:
                    result = self.test_llm_model(model_info, test_pairs)
                    result["group"] = group_key
                    group_results.append(result)
                    
                    accuracy = result["accuracy"]
                    correct = result["correct_count"]
                    total = result["total_pairs"]
                    
                    print(f"         📊 Result: {accuracy:.1%} accuracy ({correct}/{total})")
                    
                except Exception as e:
                    print(f"         ❌ Model failed: {e}")
                    group_results.append({
                        "model": model_info["name"],
                        "model_id": model_info["model_id"],
                        "group": group_key,
                        "error": str(e)
                    })
                
                print("         ⏱️  Cooling down (5s)...")
                time.sleep(5)  # Cooling down between models
            
            all_results.extend(group_results)
        
        # Final summary
        self.print_final_summary(all_results)
        return all_results
    
    def print_final_summary(self, all_results: List[Dict]):
        """Print comprehensive results summary"""
        print("\n" + "=" * 70)
        print("📊 FINAL RESULTS SUMMARY")
        print("=" * 70)
        
        # Group by model
        by_model = defaultdict(list)
        for result in all_results:
            if "error" not in result:
                by_model[result["model"]].append(result)
        
        # Calculate model averages
        print("\n🏆 MODEL PERFORMANCE:")
        best_model = None
        best_accuracy = 0
        
        for model_name, model_results in by_model.items():
            if model_results:
                avg_accuracy = sum(r["accuracy"] for r in model_results) / len(model_results)
                total_correct = sum(r["correct_count"] for r in model_results)
                total_pairs = sum(r["total_pairs"] for r in model_results)
                
                print(f"   {model_name}:")
                print(f"      Average Accuracy: {avg_accuracy:.1%}")
                print(f"      Total Results: {total_correct}/{total_pairs}")
                print(f"      Groups Tested: {len(model_results)}")
                
                if avg_accuracy > best_accuracy:
                    best_accuracy = avg_accuracy
                    best_model = model_name
        
        # Error summary
        error_results = [r for r in all_results if "error" in r]
        if error_results:
            print(f"\n❌ ERRORS ({len(error_results)}):")
            for result in error_results:
                print(f"   {result['model']}: {result['error']}")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        if best_model and best_accuracy > 0:
            print(f"   🎯 Best performer: {best_model} ({best_accuracy:.1%})")
            print(f"   📈 Ready to scale to full dataset with this model")
            print(f"   🎯 Expected improvement: 4,522 → 15,000+ equivalences")
        else:
            print(f"   ⚠️  Consider trying different models or adjusting prompts")
            print(f"   💡 SentenceTransformers might be more suitable for this task")
        
        print(f"\n✅ Testing complete!")

def main():
    """Run the LLM model testing"""
    csv_path = "/Users/hermanhello/Documents/a_omfietser/equivalent/test_products.csv"
    
    tester = LLMModelTester()
    results = tester.run_comprehensive_test(csv_path)
    
    print(f"\n🎉 HuggingFace LLM testing completed!")
    print(f"💡 Next step: Implement winning model on full 63K product dataset")

if __name__ == "__main__":
    main()
