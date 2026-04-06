#!/usr/bin/env python3
"""
Enhanced Product Matching with Fallback Support
Combines semantic similarity with smart classification rules
Falls back gracefully when SentenceTransformers is not available
"""

import pandas as pd
import re
import time
import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
from rapidfuzz import fuzz
import sys
import os

# Handle import gracefully
SENTENCE_TRANSFORMERS_AVAILABLE = False
FAISS_AVAILABLE = False

try:
    # Suppress numpy/scipy warnings
    import warnings
    warnings.filterwarnings("ignore")
    
    from sentence_transformers import SentenceTransformer
    import numpy as np
    import torch
    SENTENCE_TRANSFORMERS_AVAILABLE = True
    print("✅ SentenceTransformers available")
    
    # Suppress Intel MKL warnings first
    import os
    os.environ['MKL_THREADING_LAYER'] = 'GNU'
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
    os.environ['OMP_NUM_THREADS'] = '1'  # Prevent MKL threading conflicts
    
    # Enable Apple M1 optimizations
    if torch.backends.mps.is_available():
        print("✅ Apple M1 MPS acceleration enabled")
        # Don't set default device globally, use it only when needed
        # torch.set_default_device('mps')  # This can cause issues with sentence-transformers
    else:
        print("⚠️ MPS not available, using CPU")
        
except Exception as e:
    print(f"⚠️ SentenceTransformers not available: {e}")
    print("   Using fallback rule-based matching instead")
    import numpy as np

# Try to import faiss, fall back to sklearn if not available
try:
    import faiss
    FAISS_AVAILABLE = True
    print("✅ FAISS available for fast similarity search")
except ImportError:
    print("⚠️ FAISS not available, using sklearn NearestNeighbors instead")
    from sklearn.neighbors import NearestNeighbors
    from sklearn.metrics.pairwise import cosine_similarity

@dataclass
class EnhancedProductMatch:
    source_product_id: int
    target_product_id: int
    similarity_score: float
    equivalence_type: str
    method: str
    reasoning: str
    shop_1: str
    shop_2: str
    title_1: str
    title_2: str
    brand_1: str
    brand_2: str

class EnhancedProductMatcher:
    def __init__(self):
        self.model = None
        self.matches = []
        
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            print("🤖 Attempting to load SentenceTransformer model...")
            try:
                # Load model on CPU first, then move to MPS if available
                self.model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
                
                # Try to move to MPS if available
                if torch.backends.mps.is_available():
                    try:
                        self.model = self.model.to('mps')
                        print("✅ Model loaded successfully on Apple M1 MPS")
                    except Exception as e:
                        print(f"⚠️ MPS failed, using CPU: {e}")
                        self.model = self.model.to('cpu')
                        print("✅ Model loaded successfully on CPU")
                else:
                    print("✅ Model loaded successfully on CPU")
                    
            except Exception as e:
                print(f"⚠️ Failed to load model: {e}")
                print("   Continuing with rule-based matching only")
                self.model = None
        else:
            print("🔧 Using rule-based matching (SentenceTransformers unavailable)")
        
        # Dutch product term mappings for better matching
        self.dutch_synonyms = {
            'zero': ['zero', 'nul', 'diet', 'light'],
            'light': ['light', 'licht', 'zero', 'diet'],
            'biologisch': ['biologisch', 'bio', 'organic'],
            'komkommer': ['komkommer', 'cucumber'],
            'tomaat': ['tomaat', 'tomaten', 'tomato'],
            'melk': ['melk', 'milk'],
            'kaas': ['kaas', 'cheese'],
        }
        
    def normalize_brand(self, brand: str) -> str:
        """Enhanced brand normalization to handle spelling variations"""
        if pd.isna(brand):
            return "unknown"
            
        brand = str(brand).lower().strip()
        
        # Handle common brand variations
        brand_mappings = {
            'dr. beckmann': 'dr-beckmann',
            'dr beckmann': 'dr-beckmann', 
            'dr.beckmann': 'dr-beckmann',
            'dr beckman': 'dr-beckmann',
            'dr. beckman': 'dr-beckmann',
            'oma\'s': 'omas',
            'oma\'s soep': 'omas',
            'coca cola': 'coca-cola',
            'coca-cola': 'coca-cola',
            'cocacola': 'coca-cola',
        }
        
        # Apply mappings
        for original, normalized in brand_mappings.items():
            if original in brand:
                brand = brand.replace(original, normalized)
        
        # Remove special characters and normalize
        brand = re.sub(r'[^a-z0-9]', '', brand)
        return brand
    
    def extract_product_features(self, row) -> Dict:
        """Extract key features from product for enhanced matching"""
        title = str(row['title']).lower() if not pd.isna(row['title']) else ""
        brand = self.normalize_brand(row['brand'])
        
        # Remove shop names from title
        title_clean = re.sub(r'\b(ah|plus|jumbo|aldi)\b', '', title)
        
        # Extract key product terms
        terms = re.findall(r'\b[a-z]{2,}\b', title_clean)
        terms = [t for t in terms if t not in ['van', 'de', 'het', 'een', 'met', 'voor']]
        
        # Detect product type indicators
        is_zero_diet = any(term in title for term in ['zero', 'light', 'diet', 'sugarfree'])
        is_bio = any(term in title for term in ['biologisch', 'bio', 'organic'])
        
        return {
            'brand': brand,
            'title_clean': title_clean,
            'terms': set(terms),
            'is_zero_diet': is_zero_diet,
            'is_bio': is_bio,
            'category': row['main_category'],
            'unit': row['normalized_quantity_unit'],
            'amount': row['normalized_quantity_amount']
        }
    
    def calculate_brand_similarity(self, brand1: str, brand2: str) -> float:
        """Calculate brand similarity with fuzzy matching"""
        if brand1 == "unknown" or brand2 == "unknown":
            return 0.0
        
        if brand1 == brand2:
            return 1.0
            
        # Use fuzzy matching for brand names
        similarity = fuzz.ratio(brand1, brand2) / 100
        return similarity
    
    def calculate_rule_based_similarity(self, features1: Dict, features2: Dict) -> float:
        """Calculate similarity using rule-based approach when semantic similarity unavailable"""
        
        # Brand similarity (40% weight)
        brand_sim = self.calculate_brand_similarity(features1['brand'], features2['brand'])
        
        # Term overlap (30% weight)
        term_overlap = len(features1['terms'].intersection(features2['terms'])) / max(len(features1['terms'].union(features2['terms'])), 1)
        
        # Size similarity (20% weight)
        size_sim = 1.0 - abs(features1['amount'] - features2['amount']) / max(features1['amount'], features2['amount'])
        
        # Feature matching (10% weight)
        feature_sim = 0.0
        if features1['is_bio'] == features2['is_bio']:
            feature_sim += 0.5
        if features1['is_zero_diet'] == features2['is_zero_diet']:
            feature_sim += 0.5
        
        # Weighted combination
        overall_similarity = (brand_sim * 0.4) + (term_overlap * 0.3) + (size_sim * 0.2) + (feature_sim * 0.1)
        
        return overall_similarity
    
    def classify_product_relationship(self, features1: Dict, features2: Dict, similarity_score: float) -> Tuple[str, str]:
        """Enhanced classification using multiple signals"""
        
        # Extract key comparison metrics
        brand_similarity = self.calculate_brand_similarity(features1['brand'], features2['brand'])
        same_category = features1['category'] == features2['category']
        same_unit = features1['unit'] == features2['unit']
        
        # Size similarity
        size_similarity = 1.0 - abs(features1['amount'] - features2['amount']) / max(features1['amount'], features2['amount'])
        
        # Term overlap
        term_overlap = len(features1['terms'].intersection(features2['terms'])) / max(len(features1['terms'].union(features2['terms'])), 1)
        
        # Special feature matching
        same_bio_status = features1['is_bio'] == features2['is_bio']
        same_diet_status = features1['is_zero_diet'] == features2['is_zero_diet']
        
        # Classification logic with detailed reasoning
        
        # IDENTICAL: Same brand + high similarity + same specs
        if (brand_similarity >= 0.95 and 
            similarity_score >= 0.7 and 
            same_category and 
            same_unit and 
            size_similarity >= 0.9):
            
            reasoning = f"Brand:{brand_similarity:.2f}, Sim:{similarity_score:.2f}, Terms:{term_overlap:.2f}, Size:{size_similarity:.2f}"
            return "identical", reasoning
        
        # SIMILAR: Same brand family + good similarity OR very high similarity with same category
        elif ((brand_similarity >= 0.8 and similarity_score >= 0.6) or 
              (similarity_score >= 0.8 and same_category and same_unit)):
            
            reasoning = f"Brand:{brand_similarity:.2f}, Sim:{similarity_score:.2f}, Category:{same_category}, Size:{size_similarity:.2f}"
            return "similar", reasoning
            
        # ALTERNATIVE: Different brands but same category + decent similarity
        elif (brand_similarity < 0.8 and 
              same_category and 
              same_unit and
              similarity_score >= 0.5 and
              term_overlap >= 0.3):
            
            reasoning = f"DiffBrand, SameCat, Sim:{similarity_score:.2f}, Terms:{term_overlap:.2f}, Size:{size_similarity:.2f}"
            return "alternative", reasoning
            
        else:
            reasoning = f"NoMatch: Brand:{brand_similarity:.2f}, Sim:{similarity_score:.2f}, Category:{same_category}"
            return "no_match", reasoning
    
    def find_matches_with_semantic(self, df):
        """Find matches using SentenceTransformer semantic approach"""
        print("🔍 Extracting product features...")
        
        # Extract features for all products
        features_list = []
        for idx, row in df.iterrows():
            features = self.extract_product_features(row)
            features['idx'] = idx
            features_list.append(features)
        
        print("🧠 Generating semantic embeddings...")
        
        # Create rich descriptions for embedding
        descriptions = []
        for features in features_list:
            desc_parts = [features['brand']]
            if features['title_clean'].strip():
                desc_parts.append(features['title_clean'])
            desc_parts.append(features['category'])
            desc_parts.append(f"{features['amount']}{features['unit']}")
            
            if features['is_bio']:
                desc_parts.append("biologisch")
            if features['is_zero_diet']:
                desc_parts.append("zero diet")
                
            descriptions.append(" ".join(desc_parts))
        
        # Generate embeddings
        print(f"   Encoding {len(descriptions)} product descriptions...")
        try:
            embeddings = self.model.encode(descriptions, batch_size=32, show_progress_bar=True)
        except Exception as e:
            print(f"❌ Encoding failed: {e}")
            print("   Falling back to rule-based matching...")
            self.find_matches_rule_based(df)
            return
        
        self.process_matches(df, features_list, embeddings=embeddings)
    
    def find_matches_rule_based(self, df):
        """Find matches using rule-based approach only"""
        print("🔍 Extracting product features...")
        
        # Extract features for all products
        features_list = []
        for idx, row in df.iterrows():
            features = self.extract_product_features(row)
            features['idx'] = idx
            features_list.append(features)
        
        print("🔧 Using rule-based similarity calculation...")
        self.process_matches(df, features_list, embeddings=None)
    
    def process_matches(self, df, features_list, embeddings=None):
        """Process matches using either semantic or rule-based similarity"""
        print("🔍 Finding matches...")
        
        # Group by category + unit for efficiency
        category_groups = defaultdict(list)
        for i, features in enumerate(features_list):
            key = f"{features['category']}|{features['unit']}"
            category_groups[key].append((i, features))
        
        total_comparisons = 0
        method_name = "semantic" if embeddings is not None else "rule_based"
        
        for group_items in category_groups.values():
            if len(group_items) < 2:
                continue
                
            # Process ALL groups - no sampling, no limits (user wants complete results)
            if len(group_items) > 2000:
                print(f"  Processing extremely large group ({len(group_items)} products) - estimated {len(group_items)**2//2:,} comparisons...")
            elif len(group_items) > 1000:
                print(f"  Processing large group ({len(group_items)} products) - estimated {len(group_items)**2//2:,} comparisons...")
            elif len(group_items) > 500:
                print(f"  Processing medium group ({len(group_items)} products) - estimated {len(group_items)**2//2:,} comparisons...")
                
            # Compare products within group
            group_size = len(group_items)
            group_comparisons = 0
            
            for i, (idx1, features1) in enumerate(group_items):
                row1 = df.iloc[idx1]
                
                # Progress tracking for large groups
                if group_size > 1000 and i % 100 == 0:
                    progress_pct = (i / group_size) * 100
                    print(f"    Progress: {progress_pct:.1f}% ({i}/{group_size})")
                
                for idx2, features2 in group_items[i+1:]:
                    row2 = df.iloc[idx2]
                    group_comparisons += 1
                    
                    # Only match across different shops
                    if row1['shop_type'] == row2['shop_type']:
                        continue
                    
                    # Calculate similarity score
                    if embeddings is not None:
                        # Use semantic similarity
                        similarity_score = float(np.dot(embeddings[idx1], embeddings[idx2]))
                    else:
                        # Use rule-based similarity
                        similarity_score = self.calculate_rule_based_similarity(features1, features2)
                    
                    # Classify relationship
                    equivalence_type, reasoning = self.classify_product_relationship(
                        features1, features2, similarity_score
                    )
                    
                    total_comparisons += 1
                    
                    # Only keep meaningful matches
                    if equivalence_type != "no_match":
                        self.matches.append(EnhancedProductMatch(
                            source_product_id=int(row1['id']),
                            target_product_id=int(row2['id']),
                            similarity_score=round(similarity_score, 3),
                            equivalence_type=equivalence_type,
                            method=method_name,
                            reasoning=reasoning,
                            shop_1=row1['shop_type'],
                            shop_2=row2['shop_type'],
                            title_1=str(row1['title']),
                            title_2=str(row2['title']),
                            brand_1=str(row1['brand']) if not pd.isna(row1['brand']) else 'Unknown',
                            brand_2=str(row2['brand']) if not pd.isna(row2['brand']) else 'Unknown'
                        ))
        
        print(f"   Processed {total_comparisons:,} product comparisons")
        print(f"   Found {len(self.matches)} potential matches")
    
    def remove_duplicates(self):
        """Remove duplicate matches"""
        seen_pairs = set()
        unique_matches = []
        
        for match in self.matches:
            pair = tuple(sorted([match.source_product_id, match.target_product_id]))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                unique_matches.append(match)
        
        removed = len(self.matches) - len(unique_matches)
        if removed > 0:
            print(f"   Removed {removed} duplicate matches")
        
        self.matches = unique_matches
    
    def export_results(self) -> Optional[str]:
        """Export results to CSV"""
        if not self.matches:
            print("❌ No matches found to export")
            return None
            
        # Convert to DataFrame
        data = []
        for match in self.matches:
            data.append({
                'source_product_id': match.source_product_id,
                'target_product_id': match.target_product_id,
                'similarity_score': match.similarity_score,
                'equivalence_type': match.equivalence_type,
                'method': match.method,
                'reasoning': match.reasoning,
                'shop_1': match.shop_1,
                'shop_2': match.shop_2,
                'title_1': match.title_1,
                'title_2': match.title_2,
                'brand_1': match.brand_1,
                'brand_2': match.brand_2,
                'created_at': datetime.datetime.now().isoformat()
            })
        
        df = pd.DataFrame(data)
        df = df.sort_values('similarity_score', ascending=False)
        
        # Generate filenames
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_filename = f"enhanced_matches_{timestamp}.csv"
        db_csv = f"enhanced_matches_for_db_{timestamp}.csv"
        
        # Export full CSV
        df.to_csv(csv_filename, index=False)
        
        # Export DB-ready CSV
        minimal_df = df[['source_product_id', 'target_product_id', 'equivalence_type', 'similarity_score', 'created_at']].copy()
        minimal_df.to_csv(db_csv, index=False)
        
        # Print summary
        print(f"\n✅ ENHANCED MATCHING RESULTS:")
        print(f"   📁 Full CSV: {csv_filename}")
        print(f"   📁 DB CSV: {db_csv}")
        print(f"   📊 Total matches: {len(df)}")
        
        # Confidence breakdown
        high_conf = len(df[df['similarity_score'] >= 0.7])
        med_conf = len(df[(df['similarity_score'] >= 0.5) & (df['similarity_score'] < 0.7)])
        low_conf = len(df[df['similarity_score'] < 0.5])
        
        print(f"   🎯 High confidence (≥70%): {high_conf}")
        print(f"   🎯 Medium confidence (50-69%): {med_conf}")
        print(f"   🎯 Low confidence (<50%): {low_conf}")
        
        # Equivalence type breakdown
        print(f"\n📊 EQUIVALENCE TYPE BREAKDOWN:")
        type_counts = df['equivalence_type'].value_counts()
        for eq_type, count in type_counts.items():
            print(f"   {eq_type}: {count}")
        
        # Show top matches
        print(f"\n🔍 TOP 10 MATCHES:")
        for _, row in df.head(10).iterrows():
            print(f"   {row['similarity_score']:.3f} | {row['equivalence_type']} | {row['shop_1']} '{row['title_1'][:40]}...' ↔ {row['shop_2']} '{row['title_2'][:40]}...'")
        
        return csv_filename
    
    def run_enhanced_matching(self, csv_file: str = 'test_products.csv'):
        """Main function to run enhanced matching"""
        print(f"🚀 Enhanced Product Matching")
        print("=" * 60)
        
        # Load data
        print(f"📊 Loading data from {csv_file}...")
        try:
            df = pd.read_csv(csv_file)
        except FileNotFoundError:
            print(f"❌ File {csv_file} not found")
            return None
            
        df['brand'] = df['brand'].fillna('Unknown')
        df['title'] = df['title'].fillna('Unknown Product')
        
        print(f"   Loaded {len(df)} products")
        print("   Shop distribution:")
        for shop, count in df['shop_type'].value_counts().items():
            print(f"     {shop}: {count:,}")
        
        start_time = time.time()
        
        # Find matches (semantic or rule-based)
        if self.model is not None:
            self.find_matches_with_semantic(df)
        else:
            self.find_matches_rule_based(df)
        
        # Remove duplicates
        self.remove_duplicates()
        
        processing_time = time.time() - start_time
        print(f"\n⏱️  Processing completed in {processing_time:.1f} seconds")
        
        # Export results
        csv_file = self.export_results()
        
        if csv_file:
            print(f"\n🚀 SUCCESS! Enhanced matching completed")
            method = "semantic" if self.model is not None else "rule-based"
            print(f"   Method used: {method}")
        
        return csv_file

def main():
    """Run enhanced matching"""
    matcher = EnhancedProductMatcher()
    result = matcher.run_enhanced_matching('test_products.csv')
    
    if result:
        print(f"\n📈 INSIGHTS:")
        print(f"   🔍 Enhanced brand normalization handles spelling variations")
        print(f"   🎯 Smart classification separates identical/similar/alternative products")
        print(f"   🧠 Falls back gracefully when SentenceTransformers unavailable")
        print(f"   💰 Still FREE and runs locally - no API costs")

if __name__ == "__main__":
    main()