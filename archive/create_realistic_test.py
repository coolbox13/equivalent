#!/usr/bin/env python3
"""
Create a realistic test dataset with cross-shop products for better testing
"""

import pandas as pd
import random
from product_matching_test_simple import ProductMatchingTester

def create_realistic_test_data():
    """Create test data with simulated cross-shop equivalents"""
    
    # Load the AH data
    df = pd.read_csv('test_products.csv')
    ah_products = df[df['shop_type'] == 'AH'].head(200)  # Use first 200 AH products
    
    # Create simulated PLUS equivalents for some AH products
    plus_products = []
    
    for i, row in ah_products.head(50).iterrows():  # Convert 50 AH products to PLUS equivalents
        plus_product = row.copy()
        plus_product['id'] = 300000 + i  # Different ID range for PLUS
        plus_product['shop_type'] = 'PLUS'
        
        # Simulate realistic variations
        title = row['title']
        
        # Replace AH with PLUS in title
        title = title.replace('AH ', 'PLUS ')
        title = title.replace('AH Biologisch', 'PLUS Biologisch')
        
        # Add some natural variations
        variations = [
            lambda t: t.replace('cherry', 'kersen'),  # Different Dutch terms
            lambda t: t.replace('trostomaten', 'tomaten'),
            lambda t: t.replace('geschrapte', 'gesneden'),
            lambda t: t.replace('kleinverpakking', 'klein'),
            lambda t: t.replace('grootverpakking', 'groot'),
        ]
        
        # Apply random variation
        if random.random() < 0.3:  # 30% chance of variation
            variation = random.choice(variations)
            title = variation(title)
        
        plus_product['title'] = title
        
        # Slight price variation (±10%)
        price_variation = random.uniform(0.9, 1.1)
        plus_product['current_price'] = round(row['current_price'] * price_variation, 2)
        
        plus_products.append(plus_product)
    
    # Convert to DataFrame and combine
    plus_df = pd.DataFrame(plus_products)
    combined_df = pd.concat([ah_products, plus_df], ignore_index=True)
    
    return combined_df

def run_realistic_test():
    """Run test with realistic cross-shop data"""
    print("Creating realistic test dataset...")
    test_df = create_realistic_test_data()
    
    print(f"Test dataset contains:")
    print(test_df['shop_type'].value_counts())
    print("\nSample PLUS products:")
    plus_samples = test_df[test_df['shop_type'] == 'PLUS'].head(5)
    for _, row in plus_samples.iterrows():
        print(f"  {row['title']} - €{row['current_price']}")
    
    # Save test data
    test_df.to_csv('realistic_test_data.csv', index=False)
    
    # Run the test
    print("\n" + "="*60)
    print("RUNNING REALISTIC CROSS-SHOP TEST")
    print("="*60)
    
    # Convert to Product objects for testing
    from product_matching_test_simple import Product
    products = []
    for _, row in test_df.iterrows():
        products.append(Product(
            id=int(row['id']),
            shop_type=row['shop_type'],
            title=row['title'],
            brand=row['brand'],
            main_category=row['main_category'],
            normalized_quantity_amount=float(row['normalized_quantity_amount']),
            normalized_quantity_unit=row['normalized_quantity_unit'],
            current_price=float(row['current_price'])
        ))
    
    # Run the comparison test
    tester = ProductMatchingTester()
    tester.products = products
    results = tester.run_comparison_test(products)
    
    return results

if __name__ == "__main__":
    results = run_realistic_test()
