-- Product Essences Table Schema
-- For Omfietser supermarket comparison app
-- Stores product essence classifications separate from main products table

-- Create the product_essences table
CREATE TABLE IF NOT EXISTS product_essences (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) UNIQUE,
    essence VARCHAR(100) NOT NULL,
    confidence DECIMAL(3,2) DEFAULT 0.95 CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMP DEFAULT NOW(),
    model_version VARCHAR(50),
    processing_time_ms INTEGER,
    notes TEXT
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_product_essences_product_id ON product_essences(product_id);
CREATE INDEX IF NOT EXISTS idx_product_essences_essence ON product_essences(essence);
CREATE INDEX IF NOT EXISTS idx_product_essences_essence_confidence ON product_essences(essence, confidence);
CREATE INDEX IF NOT EXISTS idx_product_essences_created_at ON product_essences(created_at);

-- Create view for easy joining with products
CREATE OR REPLACE VIEW products_with_essences AS
SELECT 
    p.*,
    pe.essence,
    pe.confidence,
    pe.created_at as essence_created_at,
    pe.model_version
FROM products p
LEFT JOIN product_essences pe ON p.id = pe.product_id;

-- Example useful queries

-- 1. Find equivalent products across shops
-- SELECT p.title, p.shop_type, p.current_price, pe.essence
-- FROM products p
-- JOIN product_essences pe ON p.id = pe.product_id
-- WHERE pe.essence = 'shampoo' AND pe.confidence > 0.8
-- ORDER BY p.current_price;

-- 2. Compare average prices by essence across shops
-- SELECT 
--     pe.essence,
--     p.shop_type,
--     AVG(p.current_price) as avg_price,
--     COUNT(*) as product_count
-- FROM products p
-- JOIN product_essences pe ON p.id = pe.product_id
-- WHERE pe.confidence > 0.8
-- GROUP BY pe.essence, p.shop_type
-- HAVING COUNT(*) >= 2
-- ORDER BY pe.essence, avg_price;

-- 3. Find potential savings opportunities
-- WITH price_comparison AS (
--     SELECT 
--         pe.essence,
--         p.shop_type,
--         AVG(p.current_price) as avg_price
--     FROM products p
--     JOIN product_essences pe ON p.id = pe.product_id
--     WHERE pe.confidence > 0.8
--     GROUP BY pe.essence, p.shop_type
--     HAVING COUNT(*) >= 2
-- ),
-- price_spreads AS (
--     SELECT 
--         essence,
--         MAX(avg_price) - MIN(avg_price) as price_difference,
--         MIN(avg_price) as cheapest_price,
--         MAX(avg_price) as most_expensive_price
--     FROM price_comparison
--     GROUP BY essence
--     HAVING COUNT(DISTINCT shop_type) >= 2
-- )
-- SELECT 
--     essence,
--     ROUND(price_difference::numeric, 2) as savings_potential,
--     ROUND(cheapest_price::numeric, 2) as cheapest_price,
--     ROUND(most_expensive_price::numeric, 2) as most_expensive_price,
--     ROUND((price_difference / cheapest_price * 100)::numeric, 1) as savings_percentage
-- FROM price_spreads
-- WHERE price_difference > 0.50
-- ORDER BY savings_percentage DESC;

-- 4. Quality check: essences with low confidence
-- SELECT p.title, pe.essence, pe.confidence, p.main_category
-- FROM products p
-- JOIN product_essences pe ON p.id = pe.product_id
-- WHERE pe.confidence < 0.7
-- ORDER BY pe.confidence, p.main_category;

-- 5. Processing progress by category
-- SELECT 
--     p.main_category,
--     COUNT(*) as total_products,
--     COUNT(pe.product_id) as classified,
--     COUNT(*) - COUNT(pe.product_id) as remaining,
--     ROUND((COUNT(pe.product_id)::decimal / COUNT(*) * 100), 1) as completion_percentage,
--     ROUND(AVG(pe.confidence), 3) as avg_confidence
-- FROM products p
-- LEFT JOIN product_essences pe ON p.id = pe.product_id
-- GROUP BY p.main_category
-- ORDER BY completion_percentage DESC;

-- 6. Find essence groups with good cross-shop coverage
-- SELECT 
--     pe.essence,
--     p.main_category,
--     COUNT(*) as total_products,
--     COUNT(DISTINCT p.shop_type) as shop_coverage,
--     ARRAY_AGG(DISTINCT p.shop_type ORDER BY p.shop_type) as shops,
--     ROUND(AVG(pe.confidence), 3) as avg_confidence,
--     MIN(p.current_price) as min_price,
--     MAX(p.current_price) as max_price
-- FROM products p
-- JOIN product_essences pe ON p.id = pe.product_id
-- WHERE pe.confidence > 0.8
-- GROUP BY pe.essence, p.main_category
-- HAVING COUNT(*) >= 4 AND COUNT(DISTINCT p.shop_type) >= 3
-- ORDER BY shop_coverage DESC, total_products DESC;
