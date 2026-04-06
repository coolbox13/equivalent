# Omfietser Product Essence Classification System

## Overview
This system classifies products into "essences" - core product types that enable finding equivalent products across different supermarket chains (AH, JUMBO, PLUS, ALDI).

## Quick Start

### 1. Database Setup
```sql
-- Create the product_essences table
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

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_product_essences_product_id ON product_essences(product_id);
CREATE INDEX IF NOT EXISTS idx_product_essences_essence ON product_essences(essence);
CREATE INDEX IF NOT EXISTS idx_product_essences_essence_confidence ON product_essences(essence, confidence);
```

### 2. Choose Your Method

#### Option A: Claude Code (Interactive)
- Best for: Testing, manual oversight, step-by-step processing
- Requires: Claude Max account, manual copy/paste interaction
- File: `claude_code_classifier.py`

#### Option B: Anthropic API (Automated)
- Best for: Large scale processing, automation
- Requires: Anthropic API key, Claude Max recommended for rate limits
- File: `anthropic_api_classifier.py`

### 3. Configuration
Update database settings in your chosen script:
```python
db_config = {
    'host': 'localhost',
    'database': 'your_actual_db_name',
    'user': 'your_username',
    'password': 'your_password'
}
```

### 4. Installation
```bash
# Install required packages
pip install psycopg2-binary aiohttp

# For API version, set your key
export ANTHROPIC_API_KEY="your_api_key_here"
```

### 5. Run Classification
```bash
# Interactive Claude Code version
python claude_code_classifier.py

# OR automated API version  
python anthropic_api_classifier.py
```

## Rate Limiting Handling

Both scripts include sophisticated rate limiting:

### Claude Code Version:
- ✅ Manual delays between batches
- ✅ Retry logic with exponential backoff
- ✅ User confirmation before saving
- ✅ Progress tracking and recovery

### API Version:
- ✅ Automatic detection of 429 rate limit responses
- ✅ Exponential backoff with jitter
- ✅ Rate limit header parsing (reset time)
- ✅ Comprehensive error handling and logging
- ✅ Automatic retries (up to 5 attempts)
- ✅ Graceful degradation on failures

## Database Design Benefits

### Why Separate `product_essences` Table?

✅ **Performance**: No impact on main product queries
✅ **Flexibility**: Easy to rebuild/update essences without touching products
✅ **Metadata**: Track confidence, processing time, model version
✅ **Scalability**: Can add features like manual overrides, multiple models
✅ **Safety**: Original product data stays untouched

### Query Examples
```sql
-- Find equivalent products
SELECT p1.title, p1.shop_type, p1.current_price, pe.essence
FROM products p1
JOIN product_essences pe ON p1.id = pe.product_id
WHERE pe.essence = 'shampoo'
  AND pe.confidence > 0.8
ORDER BY p1.current_price;

-- Compare prices across shops for same essence
SELECT 
    pe.essence,
    p.shop_type,
    AVG(p.current_price) as avg_price,
    COUNT(*) as product_count
FROM products p
JOIN product_essences pe ON p.id = pe.product_id
WHERE pe.essence = 'deodorant spray'
GROUP BY pe.essence, p.shop_type
ORDER BY avg_price;

-- Quality check: low confidence essences
SELECT p.title, pe.essence, pe.confidence
FROM products p
JOIN product_essences pe ON p.id = pe.product_id
WHERE pe.confidence < 0.7
ORDER BY pe.confidence;
```

## Processing Strategy

### Recommended Order:
1. **Drogisterij** (~3K products) - Good variety, clear categories
2. **Zuivel** (~2K products) - Standardized products, easy matching
3. **Vlees** (~2K products) - Clear meat types
4. **Brood & Gebak** (~1.5K products) - Bread varieties
5. **Remaining categories** - Work through systematically

### Batch Sizes:
- **Claude Code**: 25 products per batch (manual review)
- **API**: 15 products per batch (automatic processing)

### Expected Timeline:
- **Testing** (500 products): 1-2 hours
- **Single category** (3K products): 4-6 hours  
- **All categories** (63K products): 2-3 days total

## Quality Control

### Automatic Quality Checks:
- Essence length validation (1-3 words)
- Brand name leakage detection
- Quantity/packaging removal verification
- Confidence scoring based on quality

### Manual Review Points:
- Sample 10-20 products from each category
- Check for over-grouping (too many products per essence)
- Check for under-grouping (too specific essences)
- Validate cross-shop equivalents make sense

### Expected Results:
- **High confidence** (>0.9): Standard products (melk, shampoo, tandpasta)
- **Medium confidence** (0.7-0.9): Complex products with variations
- **Low confidence** (<0.7): Unusual/specific products requiring review

## Monitoring & Logs

### API Version Logging:
- Processing progress and batch stats
- Rate limiting events and recovery
- Confidence scores and quality metrics
- Error handling and retry attempts
- Log file: `essence_classification.log`

### Key Metrics to Watch:
- Average confidence per category
- Processing time per batch
- Rate limit hit frequency
- Unknown essence percentage

## Next Steps After Classification

1. **Validate Quality**: Sample review of essences per category
2. **Build Matching Algorithm**: Group products by essence + similarity scoring
3. **Create Comparison API**: Endpoints for finding equivalent products
4. **Frontend Integration**: Show price comparisons for equivalent items
5. **Performance Optimization**: Index tuning, caching strategies

## Expected Impact

Current matches: **4,522**
Expected matches after essence classification: **15,000+**

### Key Improvements:
- Find equivalents across all 4 supermarket chains
- Handle Dutch compound words correctly
- Group functional equivalents (not just brand variants)
- Scale to full product catalog efficiently
- Maintain high precision while increasing recall

## Troubleshooting

### Common Issues:
1. **Database connection errors**: Check db_config settings
2. **Rate limiting**: Scripts will handle automatically
3. **Low confidence scores**: Review category-specific prompts
4. **Brand name leakage**: Essence validation will catch this
5. **API key issues**: Check ANTHROPIC_API_KEY environment variable

### Support:
- Check logs for detailed error information
- Use preview mode to test classification quality
- Start with small batches to validate results
- Monitor confidence scores and adjust prompts if needed
